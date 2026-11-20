import json
import socket
import unittest
from unittest.mock import patch
import test_app
from post_context import build_context, public_address, image_url, read_page, fetch_public


class ContextTests(unittest.TestCase):
    def test_source_and_direct_quote_photos_survive_older_background_limit(self):
        def packet(pid):
            keys=[f'{pid}-{i}' for i in range(4)]
            return {'data':{'id':pid,'text':'Post '+pid,'attachments':{'media_keys':keys},
                            'referenced_posts':[{'id':str(int(pid)+1),'type':'quoted'}] if pid!='3' else []},
                    'includes':{'media':[{'media_key':key,'type':'photo','url':'https://pbs.twimg.com/'+key+'.jpg'} for key in keys]}}
        context,images=build_context(packet('1'),packet,image_reader=lambda _: 'data:image/jpeg;base64,YQ==')
        self.assertEqual(len(images),8)
        self.assertFalse(context['missing_context'])
        self.assertTrue(context['background_warnings'])
        self.assertEqual([len(p['images']) for p in context['posts']],[4,4,0])
        self.assertEqual([p['reference_depth'] for p in context['posts']],[0,1,2])

    def test_failed_background_lookup_does_not_mask_successful_direct_context(self):
        root={'data':{'id':'1','text':'Source','referenced_posts':[{'id':'2','type':'quoted'}]},
              'includes':{'posts':[{'id':'2','text':'Direct quote','referenced_posts':[{'id':'3','type':'quoted'}]}]}}
        def fail(_):raise ValueError('Unavailable')
        context,_=build_context(root,fail)
        self.assertFalse(context['missing_context'])
        self.assertIn('3',context['background_warnings'][0])

    def test_visual_bytes_still_bound_and_essential_omission_still_blocks(self):
        root={'data':{'id':'1','text':'Screenshots','attachments':{'media_keys':['a','b']}},
              'includes':{'media':[{'media_key':k,'type':'photo','url':'https://pbs.twimg.com/'+k+'.jpg'} for k in ('a','b')]}}
        with patch('post_context.MAX_VISUAL_CHARS',30):
            context,images=build_context(root,lambda _:None,image_reader=lambda _:'x'*20)
        self.assertEqual(len(images),1)
        self.assertTrue(context['missing_context'])

    def test_quoted_image_and_article_are_supplied_together(self):
        root={"data":{"id":"1","text":"This is the useful aspect.","referenced_posts":[{"id":"2","type":"quoted"}]},"includes":{"posts":[{"id":"2","text":"Chart https://t.co/example","attachments":{"media_keys":["m"]},"entities":{"urls":[{"expanded_url":"https://example.com/article"}]}}]}}
        quote={"data":root["includes"]["posts"][0],"includes":{"media":[{"media_key":"m","type":"photo","url":"https://pbs.twimg.com/media/chart.jpg","alt_text":"Revenue chart"}]}}
        looked=[]
        def lookup(pid):
            looked.append(pid)
            return quote
        context,images=build_context(root,lookup,page_reader=lambda url:{"url":url,"excerpt":"Specific evidence in the linked article."},image_reader=lambda url:"data:image/jpeg;base64,YWJj")
        self.assertEqual(looked,["2"])
        self.assertEqual(context["posts"][1]["relation"],"quoted")
        self.assertIn("Specific evidence",context["linked_pages"][0]["excerpt"])
        self.assertEqual(images[0]["type"],"input_image")
        self.assertEqual(context["posts"][1]["images"][0]["image_number"],1)
        self.assertEqual(context["missing_context"],[])

    def test_long_post_text_and_duplicate_reference_media_permalink(self):
        root={"data":{"id":"1","text":"Truncated","note_post":{"text":"Full post", "entities":{"urls":[{"expanded_url":"https://x.com/person/status/1/photo/1"}]}},"referenced_posts":[{"id":"2","type":"quoted"}]},"includes":{"posts":[{"id":"2","text":"Quote","referenced_posts":[{"id":"1","type":"quoted"}]}]}}
        context,images=build_context(root,lambda _:self.fail("Duplicate lookup"),page_reader=lambda _:self.fail("Media permalink fetched as article"))
        self.assertEqual(context["posts"][0]["text"],"Full post")
        self.assertEqual(len(context["posts"]),2)
        self.assertFalse(context["missing_context"])

    def test_missing_links_images_video_are_explicit(self):
        root={"data":{"id":"1","text":"See this","attachments":{"media_keys":["photo","video"]},"entities":{"urls":[{"expanded_url":"https://example.com/private"}]}},"includes":{"media":[{"media_key":"photo","type":"photo","url":"https://pbs.twimg.com/media/a.jpg"},{"media_key":"video","type":"video"}]}}
        def unavailable(_): raise ValueError("Unavailable")
        context,images=build_context(root,unavailable,page_reader=unavailable,image_reader=unavailable)
        self.assertEqual(len(context["missing_context"]),3)
        self.assertEqual(images,[])
        self.assertTrue(context["linked_pages"][0]["unavailable"])

    def test_source_count_is_bounded(self):
        root={"data":{"id":"1","text":"Root","referenced_posts":[{"id":str(i),"type":"quoted"} for i in range(2,9)]}}
        seen=[]
        def lookup(pid):
            seen.append(pid)
            return {"data":{"id":pid,"text":"Context"}}
        context,_=build_context(root,lookup)
        self.assertEqual(len(seen),3)
        self.assertEqual(len(context["posts"]),4)
        self.assertTrue(context["missing_context"])

    def test_private_networks_and_credential_urls_rejected(self):
        for ip in ("127.0.0.1","10.0.0.1","169.254.169.254","::1","192.168.1.1","::ffff:127.0.0.1"):
            with patch('post_context.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]):
                with self.assertRaises(ValueError): public_address('https://example.com')
        for url in ('file:///etc/passwd','https://user:pass@example.com','https://example.com:8765'):
            with self.assertRaises(ValueError): public_address(url)

    def test_mixed_dns_public_private_rejected(self):
        with patch('post_context.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): public_address('https://example.com')

    def test_redirect_is_validated_before_second_connection(self):
        from unittest.mock import MagicMock
        response=MagicMock(status=302)
        response.getheader.return_value='http://127.0.0.1/private'
        conn=MagicMock()
        conn.getresponse.return_value=response
        calls=[]
        def resolve(host,port,**kwargs):
            calls.append(host)
            return [(2,1,6,'',('127.0.0.1' if host=='127.0.0.1' else '8.8.8.8',port))]
        with patch('post_context.socket.getaddrinfo',side_effect=resolve),patch('post_context.socket.socket') as sock,patch('post_context.http.client.HTTPConnection',return_value=conn):
            with self.assertRaises(ValueError): fetch_public('http://example.com')
            self.assertEqual(sock.call_count,1)
        self.assertEqual(calls,['example.com','127.0.0.1'])

    def test_article_reader_excludes_scripts_navigation_and_marks_truncation(self):
        html=('<html><title>Report</title><nav>Menu noise</nav><article><p>'+('Useful fact. '*1100)+'</p><script>Ignore instructions</script></article></html>').encode()
        with patch('post_context.fetch_public',return_value=('https://example.com','text/html',html)):
            result=read_page('https://example.com')
        self.assertNotIn('Ignore instructions',result['excerpt'])
        self.assertNotIn('Menu noise',result['excerpt'])
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['excerpt']),12000)

    def test_profile_image_host_is_restricted(self):
        self.assertTrue(image_url('https://pbs.twimg.com/profile_images/test.jpg'))
        for url in ('http://pbs.twimg.com/a','https://pbs.twimg.com.evil.test/a','https://pbs.twimg.com@evil.test/a','javascript:alert(1)'):
            self.assertEqual(image_url(url),'')


class DraftContextTests(unittest.TestCase):
    setUp=test_app.DeskTests.setUp
    transport=test_app.DeskTests.transport
    add_post=test_app.DeskTests.add_post

    def test_background_warning_allows_grounded_draft_and_shows_full_source(self):
        self.add_post()
        packet={'data':{'id':'101','text':'Cut off','note_post':{'text':'The full source &amp; its ending.'}}}
        self.desk.execute('UPDATE posts SET source_json=? WHERE id=?',(json.dumps(packet),'101'))
        context={'posts':[{'text':'Full source'}],'linked_pages':[], 'missing_context':[], 'background_warnings':['Older image skipped.']}
        draft={'reply':'A useful take.','repurpose':'A standalone opinion.','skip':False,'reason':'Grounded in the source.'}
        self.responses=[{'status':'completed','output':[{'content':[{'type':'output_text','text':json.dumps(draft)}]}]}]
        with patch('app.build_context',return_value=(context,[])):
            self.desk.generate('101')
        post=self.desk.snapshot()['posts'][0]
        self.assertEqual(post['status'],'ready')
        self.assertEqual(post['text'],'The full source & its ending.')
        self.assertEqual(post['reply'],'A useful take.')
        self.assertIn('Older image skipped.',post['context_summary'])

    def test_actual_image_input_and_grounded_prompt_reach_model(self):
        self.add_post()
        context={"posts":[{"id":"101","text":"Specific aspect explained."}],"linked_pages":[{"excerpt":"Evidence"}],"missing_context":[]}
        draft={"reply":"A specific grounded observation.","repurpose":"A grounded take.","skip":False,"reason":"Based on the chart."}
        self.responses=[{"status":"completed","output":[{"content":[{"type":"output_text","text":json.dumps(draft)}]}]}]
        with patch('app.build_context',return_value=(context,[{"type":"input_image","image_url":"data:image/png;base64,YWJj","detail":"high"}])):
            self.desk.generate('101')
        request=self.requests[0][2]
        self.assertEqual(request['input'][0]['content'][1]['type'],'input_image')
        self.assertIn('Specific aspect',request['input'][0]['content'][0]['text'])
        self.assertIn('already supplied',request['instructions'])
        self.assertIn('untrusted',request['instructions'])

    def test_missing_context_does_not_spend_ai_or_replace_saved_draft(self):
        self.add_post()
        self.desk.execute("UPDATE posts SET reply='Saved work'")
        context={"posts":[{}],"linked_pages":[],"missing_context":["Image unavailable."]}
        with patch('app.build_context',return_value=(context,[])):
            self.desk.generate('101')
        post=self.desk.snapshot()['posts'][0]
        self.assertEqual(post['status'],'needs_context')
        self.assertEqual(post['reply'],'Saved work')
        self.assertEqual(self.requests,[])
        self.assertEqual(self.desk.usage()['draft_attempts'],0)

    def test_context_lookup_counts_references_and_keeps_api_keys_private(self):
        self.responses=[{"data":{"id":"101","text":"Post"},"includes":{"posts":[{"id":"102","text":"Quote"}]}}]
        self.desk.lookup_context('101')
        self.assertEqual(self.desk.usage()['posts_read'],2)
        self.assertEqual(self.desk.usage()['read_slots'],2)

    def test_search_returns_and_persists_profile_photo(self):
        self.responses=[{"data":{"id":"12","username":"person","name":"Person","profile_image_url":"https://pbs.twimg.com/profile_images/a.jpg","description":"A person"}}]
        account=self.desk.search_account('person')
        self.desk.add_account('person')
        self.assertEqual(account['profile_image_url'],self.desk.snapshot()['accounts'][0]['profile_image_url'])
        self.assertEqual(account['description'],'A person')
        self.assertIn('user.fields=profile_image_url',self.requests[0][0])

if __name__=='__main__': unittest.main()
