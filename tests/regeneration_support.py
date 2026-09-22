from uuid import uuid4
from sqlalchemy import MetaData, Integer, JSON
from sqlalchemy.dialects.postgresql import JSONB
from creation_features_support import CreationFeaturesEnvironment
from app.models.tables import Base, Job, JobFile, JobEvent, RiskControlRule, JobBatch, JobQuotaReservation, PackageQuotaLedger, QuotaLedger

class RegenerationEnvironment(CreationFeaturesEnvironment):
    def __init__(self):
        super().__init__()
        meta=MetaData()
        for table in Base.metadata.tables.values():
            clone=table.to_metadata(meta)
            for column in clone.columns:
                if column.primary_key and column.name=='id':column.type=Integer()
                if isinstance(column.type,JSONB):column.type=JSON()
        for model in (Job,JobFile,JobQuotaReservation,PackageQuotaLedger,QuotaLedger):
            model.__table__.drop(self.engine)
            meta.tables[model.__tablename__].create(self.engine)
        for model in (JobEvent,RiskControlRule):meta.tables[model.__tablename__].create(self.engine)
        with self.Session() as db:
            db.add(JobBatch(id=10,user_id=1,request_id=uuid4(),batch_code='RETRY10',batch_name='原批次测试',product_name='Demo',region_name='巴西',total_count=4))
            for i,status in [(1,'failed'),(2,'failed'),(3,'download_failed'),(4,'completed')]:
                db.add(Job(id=i,user_id=1,batch_id=10,batch_index=i,provider_key_id=1,model='veo-omni-flash',seconds=10,size='720x1280',prompt=f'原提示词 {i}',product_name='Demo',region_name='巴西',status=status,error_text='上游临时失败' if status=='failed' else None,remote_task_id='old-'+str(i) if i>1 else None))
            db.flush()
            db.add(JobFile(job_id=1,file_type='reference_image_url',file_path='https://example.com/ref.png',file_name='参考图',width=720,height=1280,playable=False))
            db.add(JobQuotaReservation(job_id=1,user_id=1,source_type='personal',amount=1,status='released'))
            db.add(JobQuotaReservation(job_id=2,user_id=1,source_type='personal',amount=1,status='refunded'))
            db.add(QuotaLedger(job_id=2,user_id=1,change_amount=-1,action='debit_create_success'))
            db.add(QuotaLedger(job_id=2,user_id=1,change_amount=1,action='refund_failed_job'))
            db.commit()
