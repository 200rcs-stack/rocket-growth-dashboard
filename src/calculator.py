import pandas as pd
from config import MASTER

COST_COLUMNS=['option_id','product_name','unit_cost','other_unit_cost','commission_rate','fulfillment_unit','return_unit','lead_days','target_margin']

def master_for(inventory):
    path=MASTER/'master_cost.csv'
    if path.exists():
        master=pd.read_csv(path,dtype={'option_id':'string'})
    else: master=pd.DataFrame(columns=COST_COLUMNS)
    if inventory.empty: return master
    missing=inventory[~inventory.option_id.isin(master.option_id)].drop_duplicates('option_id')
    new=pd.DataFrame({'option_id':missing.option_id,'product_name':missing.product_name+' / '+missing.option_name.fillna('')})
    for col in COST_COLUMNS[2:]: new[col]=float('nan')
    new['lead_days']=14.0
    new['target_margin']=20.0
    master=pd.concat([master,new],ignore_index=True)
    if len(new) or not path.exists(): save_master(master)
    return master

def save_master(master):
    if master.option_id.duplicated().any(): raise ValueError('원가표 옵션 ID 중복')
    for c in COST_COLUMNS[2:]:
        master[c]=pd.to_numeric(master[c],errors='raise')
        if master[c].dropna().lt(0).any(): raise ValueError('비용·비율에 음수를 입력할 수 없습니다.')
    if master.commission_rate.dropna().gt(100).any() or master.target_margin.dropna().gt(100).any():
        raise ValueError('비율은 0~100 사이여야 합니다.')
    temp=MASTER/'master_cost.tmp'
    master.to_csv(temp,index=False,encoding='utf-8-sig')
    temp.replace(MASTER/'master_cost.csv')

def enrich(inventory,master,days=30):
    df=inventory.merge(master.drop(columns='product_name'),on='option_id',how='left',validate='many_to_one')
    df['revenue']=df[f'rev_{days}d']
    df['sold_qty']=df[f'qty_{days}d']
    df['cost_unit_total']=df.unit_cost+df.other_unit_cost
    df['model_cogs']=df.sold_qty*df.cost_unit_total
    # Explicit model only: rolling sales, MTD storage and case-based returns are not the same accounting period.
    df['model_commission']=df.revenue*df.commission_rate/100*1.1
    df['model_fulfillment']=df.sold_qty*df.fulfillment_unit
    df['contribution_before_unmatched']=df.revenue-df.model_cogs-df.model_commission-df.model_fulfillment
    df['restock_alert']=df.doc_days.notna() & df.doc_days.le(df.lead_days.fillna(14)) & df.restock_rec_qty.gt(0)
    df['out_of_stock']=df.stock_available.eq(0)
    df['long_stock']=df[['age_61_120','age_121_180','age_181_plus']].sum(axis=1,min_count=1)
    df['avg_7d']=df.rev_7d/df.qty_7d.where(df.qty_7d.gt(0))
    df['avg_30d']=df.rev_30d/df.qty_30d.where(df.qty_30d.gt(0))
    df['price_gap']=(df.avg_7d/df.avg_30d.where(df.avg_30d.gt(0))-1)*100
    df['price_alert']=df.price_gap.abs().ge(30)
    df['stock_status']=df.apply(lambda r:'품절' if r.out_of_stock else ('입고 검토' if r.restock_alert else ('장기 보관' if r.long_stock>0 else '양호')),axis=1)
    return df

def strict_total(series):
    return series.sum() if len(series)>0 and series.notna().all() else None

def claims_text(returns):
    targets=returns[returns.overdue] if not returns.empty else returns
    lines=['[로켓그로스 장기 미회수 반품 상태 및 보상내역 확인 요청]',
       '아래 반품은 수집한 보고서에서 접수 후 90일 이상 회수중으로 표시됩니다.',
       '실제 회수 완료 여부, 보상 처리 여부/금액/정산 반영일을 확인해 주세요. 이미 지급된 건은 제외해 주세요.',
       '※ 보상 미지급 확정이나 지급액 산정이 아닌 확인 요청입니다.','']
    for _,r in targets.iterrows():
        lines.append(f'반품번호 {r.return_no} | 주문번호 {r.order_no} | 옵션 {r.option_id} | 접수 {r.request_date:%Y-%m-%d} | {r.elapsed_days}일 | {r.process_status}')
    return '\n'.join(lines)
