import {costKey} from './product-costs';
type Row=Record<string,any>;
export function parseCsv(text:string){
 const rows:string[][]=[];let row:string[]=[],cell='',quoted=false;
 for(let i=0;i<text.length;i++){const c=text[i];if(c==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else if(!quoted&&cell!=='')throw Error('CSV 따옴표 형식을 확인해 주세요.');else quoted=!quoted;}
 else if(c===','&&!quoted){row.push(cell);cell='';}else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);rows.push(row);row=[];cell='';}else cell+=c;}
 if(quoted)throw Error('CSV 따옴표가 닫히지 않았습니다.');if(cell||row.length){row.push(cell);rows.push(row);}return rows;
}
export function costImport(table:unknown[][],inventory:Row[]){
 const rows=table.filter(r=>r.some(v=>v!==null&&String(v).trim()!==''));if(rows.length<2||rows.length>2001)throw Error('제목과 원가 자료를 포함해 최대 2,000개 항목을 올려 주세요.');
 const header=rows[0].map(v=>String(v??'').replace(/^\uFEFF/,'').trim());
 const find=(names:string[])=>header.findIndex(h=>names.includes(h));
 const id=find(['옵션ID','옵션 ID','option_id']),grade=find(['등급','grade']),cost=find(['매입원가','매입원가(원)','unit_cost']);
 if([id,grade,cost].includes(-1))throw Error('옵션ID, 등급, 매입원가(원) 열이 필요합니다. 양식을 내려받아 사용하세요.');
 const known=new Map(inventory.map(r=>[costKey(r),r])),seen=new Set<string>(),entries:Row[]=[],errors:string[]=[];
 rows.slice(1).forEach((r,index)=>{
  const value=r[cost];if(value==null||String(value).trim()==='')return; // Blank uploads never erase saved costs.
  const rawId=r[id];const option=String(rawId??'').trim(),g=String(r[grade]??'').trim(),key=costKey({option_id:option,grade:g});
  const text=String(value).trim().replace(/,/g,''),n=Number(text);
  let error='';if(typeof rawId==='number'&&!Number.isSafeInteger(rawId))error='옵션ID 정밀도 손실 · 셀을 텍스트로 저장하세요';
  else if(!/^\d{1,30}$/.test(option)||!known.has(key))error='미등록 옵션ID·등급';
  else if(seen.has(key))error='중복 옵션ID·등급';
  else if(!/^\d+(\.\d{1,2})?$/.test(text)||!Number.isFinite(n)||n<0||n>1e9)error='원가 형식 오류';
  seen.add(key);if(error)errors.push(`${index+2}번째 항목: ${error}`);else entries.push({...known.get(key),unit_cost:n});
 });
 if(!entries.length&&!errors.length)errors.push('입력된 매입원가가 없습니다. 빈칸은 변경하지 않습니다.');
 return {entries,errors};
}
