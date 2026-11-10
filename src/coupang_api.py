"""Read-only, documented RG API. Credentials never logged, persisted or sent to the UI."""
import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
import requests
from config import DATA, now
from src.product_prices import project_detail

PRODUCTS_PATH='/v2/providers/seller_api/apis/api/v1/marketplace/seller-products'

def authorization(access,secret,path,query,signed_date=None):
    date=signed_date or datetime.now(timezone.utc).strftime('%y%m%dT%H%M%SZ')
    signature=hmac.new(secret.encode(),(date+'GET'+path+query).encode(),hashlib.sha256).hexdigest()
    return f'CEA algorithm=HmacSHA256, access-key={access}, signed-date={date}, signature={signature}'

class CoupangReader:
    def __init__(self,vendor,access,secret):
        if not re.fullmatch(r'A[0-9A-Za-z]+',vendor): raise ValueError('A로 시작하는 판매자 ID를 확인해 주세요.')
        self.vendor,self.access,self.secret=vendor,access,secret
        self.last=0
        self.session=requests.Session()

    def request(self,path,params):
        query=urlencode(params)
        min_gap=0.18 if path.startswith(PRODUCTS_PATH+'/') else 1.1
        for attempt in range(3):
            time.sleep(max(0,min_gap-(time.monotonic()-self.last)))
            self.last=time.monotonic()
            try:
                getter=self.session.get if getattr(requests.get,'__module__','').startswith('requests') else requests.get
                response=getter('https://api-gateway.coupang.com'+path+('?' + query if query else ''),
                    headers={'Authorization':authorization(self.access,self.secret,path,query),'Content-Type':'application/json'},
                    timeout=(5,30),allow_redirects=False)
            except requests.RequestException:
                if attempt<2:
                    time.sleep(2**(attempt+1))
                    continue
                raise RuntimeError('쿠팡 API에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요.') from None
            if response.status_code==429 or response.status_code>=500:
                if attempt<2: time.sleep(2**(attempt+1)); continue
            if response.status_code!=200:
                if response.status_code==403:
                    try: reason=str(response.json().get('message','')).lower()
                    except (ValueError,TypeError,AttributeError): reason=''
                    if 'ip address' in reason and 'not allowed' in reason:
                        raise RuntimeError('쿠팡 API HTTP 403: 이 PC의 공인 IP가 아직 해당 키에 허용되지 않았습니다. 등록 IP를 확인해 주세요. 새 키 발급·연동정보 변경 직후라면 쿠팡 안내상 반영까지 최대 30분이 걸릴 수 있습니다.')
                raise RuntimeError(f'쿠팡 API HTTP {response.status_code}: 키 유효기간·판매자 ID·등록 IP·API 권한을 확인해 주세요.')
            try: payload=response.json()
            except ValueError: raise RuntimeError('쿠팡 API 응답을 읽을 수 없습니다. 기존 자료를 유지합니다.') from None
            if not isinstance(payload,dict): raise RuntimeError('쿠팡 API 응답 형식이 변경되었습니다.')
            if str(payload.get('code')) not in ['200','SUCCESS','0']:
                raise RuntimeError('쿠팡 API가 실패 응답을 반환했습니다. 권한과 조회 조건을 확인해 주세요.')
            return payload
        raise RuntimeError('쿠팡 API 재시도 횟수를 초과했습니다.')

    def pages(self,path,params):
        all_rows=[]; tokens=set()
        for _ in range(1000):
            result=self.request(path,params)
            batch=result.get('data')
            if not isinstance(batch,list): raise RuntimeError('API 응답 형식이 변경되었습니다. 기존 자료를 유지합니다.')
            all_rows.extend(batch)
            token=result.get('nextToken')
            if not token: return all_rows
            if token in tokens: raise RuntimeError('API 페이지 토큰 반복. 불완전 자료를 저장하지 않았습니다.')
            tokens.add(token); params={**params,'nextToken':token}
        raise RuntimeError('조회 페이지 상한 초과. 불완전 자료를 저장하지 않았습니다.')

    def collect(self):
        base=f'/v2/providers/rg_open_api/apis/api/v1/vendors/{self.vendor}/rg'
        inventory=self.pages(base+'/inventory/summaries',{})
        today=now().date()
        orders=self.pages(base+'/orders',{'paidDateFrom':(today-timedelta(days=29)).strftime('%Y%m%d'),'paidDateTo':today.strftime('%Y%m%d')})
        products=self.pages(PRODUCTS_PATH,
                            {'vendorId':self.vendor,'maxPerPage':100,'businessTypes':'rocketGrowth'})
        validate_snapshot(inventory,orders)
        validate_products(products)
        dest=DATA/'api_snapshot.json'
        try: previous=json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else {}
        except (OSError,ValueError): previous={}
        retained=previous.get('product_details',{}) if previous.get('vendor_id')==self.vendor else {}
        details={}; price_errors=0
        for product in products:
            ident=str(product['sellerProductId'])
            try:
                detail=self.request(PRODUCTS_PATH+'/'+ident,{})['data']
                details[ident]=project_detail(product,detail,now().isoformat())
            except (RuntimeError,KeyError,ValueError,TypeError,AttributeError):
                price_errors+=1
                if ident in retained:
                    current_ids={str((item.get('rocketGrowthItemData') or {}).get('vendorItemId')) for item in product['items']}
                    details[ident]={**retained[ident],'retained':True,'options':[item for item in retained[ident]['options'] if item['option_id'] in current_ids]}
        payload={'fetched_at':now().isoformat(),'vendor_id':self.vendor,'inventory':inventory,'orders':orders,'products':products,
            'product_details':details,'product_price_errors':price_errors,
            'paid_from':(today-timedelta(days=29)).isoformat(),'paid_to':today.isoformat(),
            'note':'주문 API는 출고일 이후 주문을 지원합니다. 상품 목록은 로켓그로스 및 혼합 운영 등록상품으로 재고 옵션 목록과 범위가 다릅니다. 미출고 주문/환불/확정정산과 다릅니다.'}
        temp=DATA/'api_snapshot.tmp'
        temp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
        temp.replace(dest)
        archive=DATA/('api_snapshot_'+now().strftime('%Y%m%d%H%M%S')+'.json')
        archive.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
        return payload


def validate_snapshot(inventory,orders):
    def numeric(value):
        return isinstance(value,(int,float)) and not isinstance(value,bool) and value>=0 and value<float('inf')
    def price(value):
        return numeric(value) or isinstance(value,str) and re.fullmatch(r'\d+(?:\.\d+)?',value) is not None
    def valid_id(value): return isinstance(value,(int,str)) and re.fullmatch(r'\d+',str(value)) is not None
    try:
        for item in inventory:
            if not valid_id(item['vendorItemId']) or not numeric(item['inventoryDetails']['totalOrderableQuantity']): raise ValueError()
        for order in orders:
            if not valid_id(order['orderId']) or not isinstance(order['orderItems'],list) or not numeric(order['paidAt']): raise ValueError()
            for item in order['orderItems']:
                if not valid_id(item['vendorItemId']) or not numeric(item['salesQuantity']) or not price(item['unitSalesPrice']): raise ValueError()
    except (ValueError,KeyError,TypeError):
        raise RuntimeError('API 필수 필드가 누락되거나 형식이 바뀌었습니다. 기존 성공 자료를 유지합니다.') from None


def validate_products(products):
    try:
        for product in products:
            if not re.fullmatch(r'\d+',str(product['sellerProductId'])): raise ValueError()
            if not isinstance(product['sellerProductName'],str) or not isinstance(product['items'],list): raise ValueError()
            for item in product['items']:
                if not isinstance(item,dict): raise ValueError()
                rg=item.get('rocketGrowthItemData') or item.get('rocketGrowthItem')
                if rg is not None and rg.get('vendorItemId') is not None and not re.fullmatch(r'\d+',str(rg['vendorItemId'])): raise ValueError()
    except (ValueError,KeyError,TypeError,AttributeError):
        raise RuntimeError('상품 API 필수 필드가 누락되거나 형식이 바뀌었습니다. 기존 성공 자료를 유지합니다.') from None
