import json
import unittest
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
import threading

import test_app
from app import DRAFT_TONES, ServiceError, make_handler


def response(reply='A fresh angle.', skip=False):
    draft = {'reply':reply,'repurpose':'A standalone angle.','skip':skip,'reason':'Grounded in the source.'}
    return {'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(draft)}]}]}


class ToneTests(unittest.TestCase):
    setUp = test_app.DeskTests.setUp
    transport = test_app.DeskTests.transport
    add_post = test_app.DeskTests.add_post

    def test_each_angle_reaches_model_and_is_saved_with_the_draft(self):
        self.add_post()
        for tone, instruction in DRAFT_TONES.items():
            with self.subTest(tone=tone):
                self.responses = [response('Draft for '+tone)]
                self.desk.generate('101', tone)
                request = self.requests[-1][2]
                self.assertIn(instruction, request['instructions'])
                self.assertIn('Selected angle for BOTH drafts: '+tone, request['instructions'])
                self.assertIn('Never deny established facts', request['instructions'])
                post = self.desk.snapshot()['posts'][0]
                self.assertEqual((post['draft_tone'],post['reply']), (tone,'Draft for '+tone))
        self.assertEqual(self.desk.usage()['draft_attempts'],len(DRAFT_TONES))

    def test_regenerate_keeps_angle_and_supplies_previous_drafts(self):
        self.add_post()
        self.desk.execute("UPDATE posts SET draft_tone='disagree',reply='Earlier reply',repurpose='Earlier take'")
        self.responses = [response()]
        self.desk.generate('101')
        request = self.requests[0][2]
        self.assertIn('Selected angle for BOTH drafts: disagree', request['instructions'])
        content = json.loads(request['input'][0]['content'][0]['text'])
        self.assertEqual(content['previous_drafts'], {'reply':'Earlier reply','repurpose':'Earlier take'})

    def test_invalid_angles_are_rejected_before_api_usage(self):
        self.add_post()
        for tone in ('invented', '', [], 1, {'tone':'disagree'}):
            with self.assertRaises(ValueError):
                self.desk.generate('101',tone)
        self.assertEqual(self.requests,[])
        self.assertEqual(self.desk.usage()['draft_attempts'],0)

    def test_skipped_angle_keeps_previous_drafts_and_their_label(self):
        self.add_post()
        self.desk.execute("UPDATE posts SET draft_tone='agreeable',reply='Keep this reply',repurpose='Keep this take'")
        self.responses = [response('',True)]
        self.desk.generate('101','controversial')
        post = self.desk.snapshot()['posts'][0]
        self.assertEqual((post['reply'],post['repurpose'],post['draft_tone']),('Keep this reply','Keep this take','agreeable'))
        self.assertEqual(post['status'],'skipped')
        self.assertIn('Previous drafts kept',post['error'])

    def test_failed_generation_keeps_draft_and_angle(self):
        self.add_post()
        self.desk.execute("UPDATE posts SET draft_tone='agreeable',reply='Keep this reply'")
        self.responses = [ServiceError('Unavailable')]
        with self.assertRaises(ServiceError):
            self.desk.generate('101','provocative')
        post = self.desk.snapshot()['posts'][0]
        self.assertEqual((post['reply'],post['draft_tone']),('Keep this reply','agreeable'))

    def test_edit_during_generation_wins_over_new_angle(self):
        self.add_post()
        def edited(url,token,body=None):
            self.desk.execute("UPDATE posts SET reply='A newer edit'")
            return response()
        self.desk.transport = edited
        with self.assertRaisesRegex(ServiceError,'edited'):
            self.desk.generate('101','disagree')
        post = self.desk.snapshot()['posts'][0]
        self.assertEqual((post['reply'],post['draft_tone']),('A newer edit','auto'))

    def test_http_draft_route_passes_selected_angle(self):
        self.add_post()
        self.responses = [response()]
        server = ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.desk))
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        req = Request(f'http://127.0.0.1:{server.server_port}/api/draft',data=json.dumps({'id':'101','tone':'provocative'}).encode(),headers={'Content-Type':'application/json','X-Desk-Token':self.desk.csrf})
        with urlopen(req) as result:
            self.assertEqual(result.status,200)
        self.assertEqual(self.desk.snapshot()['posts'][0]['draft_tone'],'provocative')


if __name__ == '__main__':
    unittest.main()
