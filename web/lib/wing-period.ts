export type WingRange={start:string;end:string};
export const WING_MIN='2024-10-01';
const iso=(d:Date)=>d.toISOString().slice(0,10);
const day=86400000;
const validDate=(v:unknown):v is string=>{
 if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(v))return false;
 const ms=Date.parse(v+'T00:00:00Z');
 return Number.isFinite(ms)&&iso(new Date(ms))===v;
};
export function wingPresets(now=new Date()){
 const kst=new Date(now.getTime()+9*3600000);
 const y=kst.getUTCFullYear(),m=kst.getUTCMonth(),d=kst.getUTCDate();
 const end=iso(new Date(Date.UTC(y,m,d)-day));
 return {
  week:{start:iso(new Date(Date.UTC(y,m,d)-7*day)),end},
  last:{start:iso(new Date(Date.UTC(y,m-1,1))),end:iso(new Date(Date.UTC(y,m,1)-day))},
  month:{start:iso(new Date(Date.UTC(y,m,1))),end},
 };
}
export function wingRange(start:unknown,end:unknown,now=new Date()):WingRange|null{
 return validDate(start)&&validDate(end)&&start>=WING_MIN&&end<=wingPresets(now).week.end&&start<=end?{start,end}:null;
}
export function exactWingRow(rows:any[],range:WingRange){
 return (rows||[]).filter(r=>r?.start===range.start&&r?.end===range.end)
  .sort((a,b)=>(Date.parse(b.captured_at)||0)-(Date.parse(a.captured_at)||0))[0];
}
