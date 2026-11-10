type Row=Record<string,any>;
export const productNameKey=(value:unknown)=>typeof value==='string'?value.normalize('NFKC').replace(/\s+/g,' ').trim():'';
export function familyIdentity(row:Row){
 const name=productNameKey(row.product_name??row.sellerProductName??row.product);
 if(name&&!/미연결|미확인|^—$/.test(name))return 'name:'+name;
 return row.product_id?'id:'+String(row.product_id):row.option_id?'option:'+String(row.option_id):'';
}
export function productFamilies(rows:Row[]){
 const keys=[...new Set(rows.map(familyIdentity).filter(Boolean))].sort();
 return Object.fromEntries(keys.map((key,index)=>{
  let hash=2166136261;for(const char of key)hash=Math.imul(hash^char.charCodeAt(0),16777619)>>>0;
  const hue=hash%360;
  return [key,{key,label:'상품 '+String(index+1).padStart(2,'0'),color:`hsl(${hue} 60% 30%)`,tint:`hsl(${hue} 58% 96%)`}];
 }));
}
