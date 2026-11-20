import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_app
from post_context import build_context
from video_context import choose_variant, extract_video, read_video, video_url, request_transcription


class VideoTests(unittest.TestCase):
    def test_variant_uses_public_x_mp4_with_bounded_bitrate(self):
        variants=[{'content_type':'application/x-mpegURL','url':'https://video.twimg.com/a.m3u8'},
                  {'content_type':'video/mp4','bit_rate':256000,'url':'https://video.twimg.com/low.mp4'},
                  {'content_type':'video/mp4','bit_rate':832000,'url':'https://video.twimg.com/medium.mp4'},
                  {'content_type':'video/mp4','bit_rate':2176000,'url':'https://video.twimg.com/high.mp4'}]
        self.assertEqual(choose_variant({'variants':variants}),'https://video.twimg.com/medium.mp4')
        for value in ['http://video.twimg.com/a.mp4','https://video.twimg.com.evil/a.mp4','https://127.0.0.1/a.mp4','file:///private/a.mp4','https://user@video.twimg.com/a.mp4']:
            self.assertFalse(video_url(value))
        with self.assertRaises(ValueError):choose_variant({'variants':[]})

    def test_overlong_clip_is_not_downloaded_or_partially_analysed(self):
        with patch('video_context.shutil.which',return_value='/ffmpeg'),patch('video_context.fetch_public') as fetch:
            with self.assertRaisesRegex(ValueError,'five minutes'):read_video({'duration_ms':301000},lambda _:None)
        fetch.assert_not_called()

    def test_quoted_video_frames_and_transcript_are_bound_to_original_speaker(self):
        root={'data':{'id':'1','text':'That is exactly how demos feel','referenced_posts':[{'id':'2','type':'quoted'}]},
              'includes':{'posts':[{'id':'2','text':'Original clip','attachments':{'media_keys':['v']}}],
                          'media':[{'media_key':'v','type':'video','variants':[{'url':'x'}]}]}}
        video={'duration_seconds':3,'transcript':'The demo only works on my laptop','audio_status':'transcribed'}
        context,images=build_context(root,lambda _:self.fail('Unexpected lookup'),video_reader=lambda _: (video,[{'seconds':0,'image_url':'data:image/jpeg;base64,YQ=='},{'seconds':2.9,'image_url':'data:image/jpeg;base64,Yg=='}]))
        self.assertEqual(context['posts'][0]['text'],'That is exactly how demos feel')
        clip=context['posts'][1]['videos'][0]
        self.assertEqual(clip['transcript'],video['transcript'])
        self.assertEqual(clip['frames'][1],{'image_number':2,'seconds':2.9})
        self.assertEqual(images[0]['type'],'input_image')
        self.assertFalse(context['missing_context'])

    def test_video_failure_is_missing_context_not_a_thumbnail_substitute(self):
        root={'data':{'id':'1','text':'Clip','attachments':{'media_keys':['v']}},'includes':{'media':[{'media_key':'v','type':'video'}]}}
        def fail(_):raise ValueError('Audio unavailable')
        context,images=build_context(root,lambda _:None,video_reader=fail)
        self.assertIn('Audio unavailable',context['missing_context'][0])
        self.assertFalse(images)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_real_media_decode_covers_start_end_and_extracts_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            path=folder/'fixture.mp4'
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=160x120:rate=10','-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-y',str(path)],check=True,capture_output=True,timeout=20)
            duration,frames,audio=extract_video(path,folder)
            self.assertAlmostEqual(duration,2,delta=.2)
            self.assertEqual(frames[0]['seconds'],0)
            self.assertGreater(frames[-1]['seconds'],duration-.2)
            self.assertTrue(all(f['image_url'].startswith('data:image/jpeg;base64,') for f in frames))
            self.assertTrue(audio.stat().st_size>0)

    def test_transcription_uses_multipart_file_not_a_filename_or_url(self):
        from io import BytesIO
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'speech.mp3';path.write_bytes(b'fixture audio')
            with patch('video_context.urlopen',return_value=BytesIO(b'{"text":"Actual words"}')) as send:
                self.assertEqual(request_transcription(path,'test-key'),'Actual words')
            request=send.call_args.args[0]
            self.assertEqual(request.full_url,'https://api.openai.com/v1/audio/transcriptions')
            self.assertIn(b'fixture audio',request.data)
            self.assertIn(b'gpt-transcribe',request.data)


class AudioBudgetTests(unittest.TestCase):
    setUp=test_app.DeskTests.setUp
    transport=test_app.DeskTests.transport

    def test_cache_avoids_repeated_charge_and_budget_blocks_new_audio(self):
        path=Path(self.temp.name)/'speech.mp3';path.write_bytes(b'sound')
        self.desk.save_settings({'daily_drafts':1})
        with patch('app.request_transcription',return_value='Words spoken') as call:
            self.assertEqual(self.desk.transcribe_audio(path),'Words spoken')
            self.assertEqual(self.desk.transcribe_audio(path),'Words spoken')
            self.assertEqual(call.call_count,1)
            path.write_bytes(b'different sound')
            with self.assertRaisesRegex(ValueError,'allowance'):self.desk.transcribe_audio(path)
        self.assertEqual(self.desk.usage()['transcription_attempts'],1)

    def test_failed_transcription_counts_attempt_and_is_not_cached(self):
        path=Path(self.temp.name)/'speech.mp3';path.write_bytes(b'sound')
        with patch('app.request_transcription',side_effect=ValueError('Unavailable')):
            with self.assertRaises(ValueError):self.desk.transcribe_audio(path)
        self.assertEqual(self.desk.usage()['transcription_attempts'],1)
        self.assertEqual(self.desk.rows('SELECT * FROM transcripts'),[])

if __name__=='__main__':unittest.main()
