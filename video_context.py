"""Read short X videos as timestamped frames plus a speech transcript."""
import base64
import json
import math
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from post_context import fetch_public

MAX_SECONDS = 300
MAX_BYTES = 80_000_000
TRANSCRIBE_MODEL = "gpt-transcribe"


def video_url(url):
    try:
        p = urlparse(url or "")
        return p.scheme == "https" and p.hostname == "video.twimg.com" and p.port in (None,443) and not p.username and p.path.endswith('.mp4')
    except ValueError:
        return False


def choose_variant(media):
    variants = [v for v in media.get('variants',[]) if v.get('content_type') == 'video/mp4' and video_url(v.get('url'))]
    if not variants:
        raise ValueError('X did not provide a downloadable MP4 video.')
    def rate(v): return int(v.get('bit_rate',v.get('bitrate',0)))
    moderate = [v for v in variants if rate(v) <= 1_500_000]
    return (max(moderate,key=rate) if moderate else min(variants,key=rate))['url']


def run_media(command, timeout=45):
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        # ffmpeg logs may embed file metadata; return a bounded explanation instead.
        raise ValueError('The video could not be decoded within the processing limit.') from None


def extract_video(path, folder):
    # No network or external track references are allowed in a downloaded media file.
    input_args = ['-protocol_whitelist','file,pipe','-f','mov','-enable_drefs','0','-use_absolute_path','0','-i',str(path)]
    probe = run_media(['ffprobe','-v','error',*input_args,'-show_format','-show_streams','-of','json'])
    info = json.loads(probe.stdout)
    duration = float(info.get('format',{}).get('duration',0))
    if not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS:
        raise ValueError('Video must be no longer than five minutes; longer clips need manual review.')
    streams = info.get('streams',[])
    if not any(s.get('codec_type') == 'video' for s in streams):
        raise ValueError('The attachment has no readable video track.')
    count = min(24,max(2,math.ceil(duration)))
    times = [round(i * max(0,duration - min(.1,duration/10)) / (count-1),3) for i in range(count)]
    frames = []
    for i, seconds in enumerate(times):
        output = folder / f'frame-{i}.jpg'
        run_media(['ffmpeg','-hide_banner','-loglevel','error','-nostdin', '-ss',str(seconds),*input_args,'-map','0:v:0','-frames:v','1','-vf',"scale='min(960,iw)':-2",'-q:v','3','-threads','1','-y',str(output)],timeout=12)
        if not output.exists() or output.stat().st_size == 0:
            raise ValueError('A video frame could not be read; review the clip manually.')
        frames.append({'seconds':seconds,'image_url':'data:image/jpeg;base64,'+base64.b64encode(output.read_bytes()).decode()})
    audio = None
    if any(s.get('codec_type') == 'audio' for s in streams):
        audio = folder / 'speech.mp3'
        run_media(['ffmpeg','-hide_banner','-loglevel','error','-nostdin',*input_args,'-map','0:a:0','-vn','-ac','1','-ar','16000','-c:a','libmp3lame','-b:a','64k','-threads','1','-y',str(audio)])
    return duration, frames, audio


def request_transcription(path, token):
    audio = Path(path).read_bytes()
    if not 0 < len(audio) <= 25_000_000:
        raise ValueError('Audio exceeds the transcription size limit.')
    boundary = 'draftdesk-' + secrets.token_hex(16)
    parts = []
    for name,value in [('model',TRANSCRIBE_MODEL),('response_format','json')]:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'.encode()+audio+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    request = Request('https://api.openai.com/v1/audio/transcriptions', data=b''.join(parts), headers={'Authorization':'Bearer '+token, 'Content-Type':'multipart/form-data; boundary='+boundary})
    try:
        with urlopen(request,timeout=90) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise ValueError(f'Audio transcription failed (HTTP {exc.code}); check API access or retry.') from None
    except (URLError,OSError,ValueError):
        raise ValueError('Audio transcription could not finish. Retry or review the clip manually.') from None
    if not isinstance(result,dict) or not isinstance(result.get('text'),str) or result.get('error'):
        raise ValueError('Audio transcription returned no usable result.')
    return result['text']


def read_video(media, transcribe):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('Install FFmpeg to read videos on this Mac.')
    if float(media.get('duration_ms',0)) > MAX_SECONDS*1000:
        raise ValueError('Video exceeds five minutes; it has not been analysed.')
    url = choose_variant(media)
    _, kind, data = fetch_public(url,MAX_BYTES,timeout=60,allowed_hosts={'video.twimg.com'})
    if kind not in ('video/mp4','application/octet-stream'):
        raise ValueError('X did not return a supported MP4 video.')
    with tempfile.TemporaryDirectory(prefix='draft-desk-video-') as temporary:
        folder=Path(temporary)
        path=folder/'clip.mp4'
        path.write_bytes(data)
        duration,frames,audio=extract_video(path,folder)
        transcript=transcribe(audio) if audio else ''
    return {'media_key':media.get('media_key'), 'duration_seconds':round(duration,3), 'transcript':transcript,
            'audio_status':('transcribed' if transcript.strip() else 'no intelligible speech returned') if audio else 'no audio track',
            'coverage':'Frames sampled across the full clip; speech transcribed when present. Fast actions, tone and non-speech sounds may be missed.'},frames
