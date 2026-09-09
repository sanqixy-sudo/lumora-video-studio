import tempfile
import unittest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models.tables import Job, JobFile
from app.api.user.routes import _batch_summary_map, _assert_requested_key_available
from fastapi import HTTPException
from unittest.mock import MagicMock


class BatchAvailabilityTests(unittest.TestCase):
    def test_summary_requires_completed_job_and_existing_file(self):
        engine=create_engine('sqlite:///:memory:')
        Job.__table__.create(engine); JobFile.__table__.create(engine)
        with tempfile.TemporaryDirectory() as folder, Session(engine) as db:
            output=Path(folder)/'output.mp4'; output.write_bytes(b'mock-video')
            db.add_all([Job(id=1,user_id=1,batch_id=7,prompt='a',status='completed'),Job(id=2,user_id=1,batch_id=7,prompt='b',status='completed'),Job(id=3,user_id=1,batch_id=7,prompt='c',status='remote_completed'),Job(id=4,user_id=1,batch_id=8,prompt='d',status='completed')]); db.flush()
            for file_id,job_id,file_path in [(1,1,str(output)),(2,2,str(Path(folder)/'missing.mp4')),(3,3,str(output)),(4,4,str(output))]:
                db.add(JobFile(id=file_id,job_id=job_id,file_type='output_video',file_path=file_path,file_name='video.mp4',playable=True))
            db.commit()
            summary=_batch_summary_map(db,{7,8})
            self.assertEqual(summary[7]['completed_count'],2)
            self.assertEqual(summary[7]['active_count'],1)
            self.assertEqual(summary[7]['downloadable_count'],1)
            self.assertEqual(summary[8]['downloadable_count'],1)
            output.unlink()
            self.assertEqual(_batch_summary_map(db,{7})[7]['downloadable_count'],0)
        engine.dispose()

    def test_retired_key_is_rejected_before_risk_filter_can_skip_selection(self):
        db=MagicMock(); db.query.return_value.filter.return_value.first.return_value=MagicMock(provider_name='apipod_grok')
        with self.assertRaises(HTTPException): _assert_requested_key_available(db,9)

if __name__=='__main__': unittest.main()
