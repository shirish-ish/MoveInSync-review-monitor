import contextlib
import importlib.util
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('collector', Path(__file__).resolve().parents[1]/'Pull_reviews.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
END = datetime(2026, 10, 29, 12)
START = END - timedelta(days=365)

def row(key, date, score=1, text='app keeps crashing'):
    r = {key: '' for key in m.FIELDS}
    r.update(reviewId=key, at=str(date), score=str(score), content=text,
             thumbsUpCount='0', appVersion='12.20.0')
    return r

META = dict(score=4.1, ratings=12345)

class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = self.root/'reviews_raw.csv'
        m.write_csv(self.raw, [row('a', END-timedelta(days=5)), row('archive', datetime(2019,1,1))])
        self.before = self.raw.read_bytes()
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()

    def tearDown(self):
        self.silence.__exit__(None,None,None)
        self.temp.cleanup()

    def fetch(self, token, count):
        return [row('a', END-timedelta(days=5), 5), row('new', END-timedelta(days=6)),
                row('boundary', START-timedelta(seconds=1))], SimpleNamespace(token=None)

    def test_merge_backup_repeat_and_report(self):
        s = m.run(self.root, 20000, self.fetch, lambda:META, END)
        self.assertEqual((s['new'],s['updated'],s['total']), (2,1,4))
        self.assertEqual(len(m.load_existing(self.raw)),4)
        d = next((self.root/'snapshots').iterdir())
        self.assertEqual((d/'reviews_before.csv').read_bytes(),self.before)
        result = json.loads((d/'review_summary.json').read_text())
        self.assertEqual(result['metrics']['n'],2)
        self.assertEqual(result['metrics']['average'],3)
        self.assertEqual(result['low_rating_n'],1)
        self.assertTrue((self.root/'latest_report.html').exists())
        s2 = m.run(self.root, 20000, self.fetch, lambda:META, END)
        self.assertEqual((s2['new'],s2['updated']), (0,0))

    def test_window_boundaries_and_future(self):
        records = [row(str(i),d) for i,d in enumerate([START-timedelta(seconds=1),START,END,END+timedelta(seconds=1)])]
        year,_,_,result = m.analyse(records,START,END,{},'test')
        self.assertEqual({r['reviewId'] for r in year},{'1','2'})

    def test_cap_does_not_overwrite(self):
        with self.assertRaises(RuntimeError):
            m.run(self.root,1,lambda t,c:([row('new',END)],SimpleNamespace(token='more')),lambda:META,END)
        self.assertEqual(self.raw.read_bytes(), self.before)
        self.assertFalse((self.root/'latest_report.html').exists())
        self.assertFalse((self.root/'reviews_refresh.lock').exists())

    def test_empty_response_does_not_overwrite(self):
        with self.assertRaises(RuntimeError):
            m.run(self.root,20000,lambda t,c:([],None),lambda:META,END)
        self.assertEqual(self.raw.read_bytes(),self.before)

    def test_network_error_does_not_overwrite(self):
        def fail(t,c): raise ConnectionError('test network failure')
        with patch.object(m.time,'sleep'),self.assertRaises(ConnectionError):
            m.run(self.root,20000,fail,lambda:META,END)
        self.assertEqual(self.raw.read_bytes(),self.before)

    def test_duplicate_pages_fail(self):
        with self.assertRaises(RuntimeError):
            m.collect(lambda t,c:([row('same',END)],SimpleNamespace(token='repeat')),20,START)

    def test_schema_failure(self):
        with self.assertRaises(ValueError):
            m.run(self.root,20,lambda t,c:([{'reviewId':'bad'}],None),lambda:META,END)
        self.assertEqual(self.raw.read_bytes(),self.before)

    def test_empty_window(self):
        year,lab,q,result = m.analyse([row('old',datetime(2019,1,1))],START,END,{},'offline')
        self.assertIsNone(result['metrics']['average'])
        self.assertEqual(result['recommendations'],[])
        m.save_analysis(self.root,year,lab,q,result)
        self.assertIn('No playbook matched',(self.root/'report.html').read_text())

    def test_known_misclassifications(self):
        for text in ['they keep assigning cabs late','my logout cab was scheduled at 6 pm']:
            self.assertNotIn('Authentication', m.classify(text))
        self.assertNotIn('App stability',m.classify('driver exceeds speed limit, slow down'))
        self.assertIn('OTP context unclear',m.classify('OTP not received'))
        self.assertIn('Boarding',m.classify('view otp behind seat belt check'))
        self.assertIn('Authentication',m.classify('not able to login, OTP not received'))

    def test_html_escapes_review_content(self):
        data = m.analyse([row('x',END,text='app crash <script>alert(1)</script>')],START,END,{},'offline')
        m.save_analysis(self.root,*data)
        html = (self.root/'report.html').read_text()
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)

    def test_source_end_warning(self):
        s=m.run(self.root,20000,lambda t,c:([row('new',END)],SimpleNamespace(token=None)),lambda:META,END)
        self.assertEqual(s['stop_reason'],'source_end_unverified')

    def test_context_and_generic_feedback(self):
        checks = [
            ('map gets stuck and location is wrong','Tracking and ETA'),
            ('location shows one or two hours ago','Tracking and ETA'),
            ('driver arrival shows 5 mins then changes to 30 mins','Tracking and ETA'),
            ('Cabbies do not communicate on arrival','Driver contact'),
            ('transport help team does not help','Support'),
            ('no way to rate 1, 2, or 3','Feedback controls'),
            ('logouting sometimes and not getting login','Authentication'),
            ('login nhi ho rha','Authentication'),
            ('parking booking is still showing previous days slot','Workplace / parking'),
            ('desk allocation removed from booking','Workplace / parking'),
            ('metro ticket booked but no QR','Metro tickets'),
            ('lost signal and driver details disappeared','Connectivity / offline access'),
            ('too many notifications','Notifications'),
            ('microphone access is mandatory','Permissions'),
            ('cannot edit destination','Navigation / address UX'),
            ('SOS does not work','Safety investigation'),
        ]
        for text, expected in checks:
            with self.subTest(text=text): self.assertIn(expected,m.classify(text))
        for text in ['parking booking stale','metro ticket booked but no QR','desk booking disappeared']:
            self.assertNotIn('Booking reliability', m.classify(text))
        self.assertNotIn('Boarding',m.classify('metro ticket booked but no QR'))
        self.assertNotIn('Support',m.classify('does not support laptop'))
        self.assertNotIn('App stability',m.classify('pickup time changes automatically'))
        self.assertNotIn('App stability',m.classify('please slow down driver exceeds speed limit'))
        self.assertEqual(m.feedback_status('worst app ever',{}),'general_feedback_no_detail')
        self.assertEqual(m.feedback_status('SOS does not work',m.classify('SOS does not work')),'rule_matched')
        self.assertEqual(m.feedback_status('good app',{}),'rating_text_mismatch')
        self.assertEqual(m.feedback_status('my issue is not described by your categories',{}),'unclassified_needs_review')

    def test_generic_feedback_retained_and_queue_reconciles(self):
        records = [row('general',END,text='worst app ever'),row('unknown',END,text='a mystery specific problem'),
                   row('safety',END,text='SOS does not work'),row('mismatch',END,text='good app')]
        year,lab,queue,r=m.analyse(records,START,END,{},'test')
        self.assertEqual(len(lab),4)
        self.assertEqual(len(queue),3)
        self.assertEqual(sum(r['status_counts'].values()),4)
        self.assertEqual(r['status_counts']['general_feedback_no_detail'],1)

if __name__=='__main__': unittest.main()
