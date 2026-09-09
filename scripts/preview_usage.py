"""Fictional monthly report data. No database or upstream access."""
import calendar
from datetime import date
from types import SimpleNamespace

def build_usage_preview(user, month='2026-06', query='', hide_zero=False, empty=False):
    year, number=map(int,month.split('-'))
    date(year,number,1)
    days=list(range(1,calendar.monthrange(year,number)[1]+1))
    previous=(year-1,12) if number==1 else (year,number-1)
    following=(year+1,1) if number==12 else (year,number+1)
    rows=[]
    for index in range(24):
        account=SimpleNamespace(**{**vars(user),'id':index+2,'username':f'creator{index+1:02d}','display_name':['创作一组','品牌视觉组','内容制作组','广告投放组'][index%4]+f' · {index+1:02d}'})
        daily=[]
        for day in days:
            real=0 if (index+day)%7==0 else (index*7+day*11)%68
            adjusted=index%8==0 and day in [3,18]
            daily.append({'date':f'{year:04d}-{number:02d}-{day:02d}','real':real,'display':real+5 if adjusted else real,'is_override':adjusted,'note':'模拟调整' if adjusted else ''})
        row=SimpleNamespace(user=account,monthly_display=sum(d['display'] for d in daily),monthly_real=sum(d['real'] for d in daily),daily=daily)
        if empty or query and query.lower() not in account.username.lower() and query!=str(account.id):continue
        if hide_zero and row.monthly_display==0:continue
        rows.append(row)
    totals=[{'day':day,'real':sum(r.daily[day-1]['real'] for r in rows),'display':sum(r.daily[day-1]['display'] for r in rows)} for day in days] if rows else []
    return {'month':f'{year:04d}-{number:02d}','prev_month':f'{previous[0]:04d}-{previous[1]:02d}','next_month':f'{following[0]:04d}-{following[1]:02d}','days':days,'rows':rows,'daily_totals':totals,'real_total':sum(r.monthly_real for r in rows),'display_total':sum(r.monthly_display for r in rows),'override_count':sum(d['is_override'] for r in rows for d in r.daily),'usage_query':query,'hide_zero':hide_zero}
