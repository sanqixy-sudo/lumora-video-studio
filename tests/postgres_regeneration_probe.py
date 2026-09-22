"""Run only in a disposable PostgreSQL database with no worker process."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models.tables import Base,User,ProviderKey,QuotaWallet,JobBatch,Job,JobQuotaReservation
from app.services.job_regeneration import regenerate_failed_jobs

engine=create_engine(settings.database_url)
assert engine.url.database=='regeneration_test', 'Disposable test database required'
Base.metadata.create_all(engine)
Session=sessionmaker(engine,expire_on_commit=False)
with Session() as db:
    db.add(User(id=1,username='retry-test',password_hash='unused',role='user',status='active'))
    db.add(ProviderKey(id=1,name='test',provider_name='veo_omni',key_masked='***',key_encrypted='unused',model_id_10s='veo-omni-flash',status='active'))
    db.flush()
    db.add(QuotaWallet(user_id=1,remaining_quota=10,reserved_quota=0,total_granted=10))
    db.add(JobBatch(id=1,user_id=1,request_id=uuid4(),batch_code='PG-RETRY',total_count=1))
    db.flush()
    job=Job(user_id=1,batch_id=1,batch_index=1,provider_key_id=1,model='veo-omni-flash',seconds=10,size='720x1280',prompt='test',status='failed')
    db.add(job);db.commit();source_id=job.id
barrier=Barrier(2)
def click():
    with Session() as db:
        user=db.get(User,1);barrier.wait(timeout=10)
        return regenerate_failed_jobs(db,user,1,[source_id])[0].id
with ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(lambda _:click(),range(2)))
assert results[0]==results[1],results
with Session() as db:
    assert db.query(Job).count()==2
    assert db.query(JobQuotaReservation).count()==1
    assert db.query(QuotaWallet).one().reserved_quota==1
print('POSTGRES_CONCURRENT_REGENERATION_OK: two simultaneous requests, one retry, one quota reservation')
