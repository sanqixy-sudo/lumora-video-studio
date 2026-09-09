import unittest
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.tables import Job, JobBatch, User, JobFile
from app.api.admin.routes import _job_status_tabs, jobs_page


class AdminBatchScopeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        for model in [Job, JobBatch, User, JobFile]:
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([
            JobBatch(id=7,user_id=1,request_id=uuid4(),batch_code='batch-seven',total_count=2),
            JobBatch(id=8,user_id=1,request_id=uuid4(),batch_code='batch-eight',total_count=1),
            Job(id=1,user_id=1,batch_id=7,prompt='a',status='completed'),
            Job(id=2,user_id=1,batch_id=7,prompt='b',status='queued'),
            Job(id=3,user_id=1,batch_id=8,prompt='c',status='failed'),
            Job(id=4,user_id=2,prompt='d',status='completed'),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_status_counts_stay_inside_batch(self):
        counts={row['key']:row['count'] for row in _job_status_tabs(self.db,None,'all',7)}
        self.assertEqual(counts['all'],2)
        self.assertEqual(counts['completed'],1)
        self.assertEqual(counts['failed'],0)

    def render_page(self,batch_id=None,status='all'):
        with patch('app.api.admin.routes.render',side_effect=lambda *args,**kw:kw), patch('app.api.admin.routes.get_system_setting_int',return_value=3), patch('app.api.admin.routes.queue_text',return_value='mock'), patch('app.api.admin.routes.attach_display_names'):
            return jobs_page(request=None,page=1,per_page=20,user=None,status=status,batch_id=batch_id,current_user=User(id=9,role='admin'),db=self.db)

    def test_batch_scope_and_default_all_tasks(self):
        self.assertEqual({job.id for job in self.render_page()['jobs']},{1,2,3,4})
        scoped=self.render_page(7)
        self.assertEqual({job.id for job in scoped['jobs']},{1,2})
        self.assertEqual(scoped['selected_batch'].id,7)
        self.assertEqual(scoped['selected_batch_summary']['total'],2)
        self.assertEqual([job.id for job in self.render_page(7,'completed')['jobs']],[1])

    def test_unknown_batch_does_not_fall_back_to_all_tasks(self):
        with self.assertRaises(HTTPException) as error:
            self.render_page(99)
        self.assertEqual(error.exception.status_code,404)
