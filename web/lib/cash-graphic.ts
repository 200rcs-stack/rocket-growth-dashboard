import type {ProfitRow} from './profit-data';
const numeric=(v:any):v is number=>typeof v==='number'&&Number.isFinite(v);
export function cashGraphic(profit:ProfitRow){
 const parts=profit.cost_components||[];
 const valid=profit.cost_parts_complete===true&&numeric(profit.wing_cost)&&profit.wing_cost>0&&parts.length>0&&parts.every((part:ProfitRow)=>numeric(part.amount)&&part.amount>=0);
 const reconciled=valid&&Math.abs(parts.reduce((sum:number,part:ProfitRow)=>sum+part.amount,0)-profit.wing_cost)<1;
 let offset=0;
 const segments=parts.map((part:ProfitRow)=>{const share=reconciled?part.amount/profit.wing_cost:null;const segment={...part,share,offset};if(share!==null)offset+=share;return segment});
 const max=Math.max(profit.total_income||0,profit.wing_cost||0);
 return {segments,available:reconciled,
   income_width:numeric(profit.total_income)&&profit.total_income>=0&&max>0?profit.total_income/max*100:null,
   cost_width:numeric(profit.wing_cost)&&profit.wing_cost>=0&&max>0?profit.wing_cost/max*100:null,
   expense_ratio:numeric(profit.total_income)&&profit.total_income>0&&numeric(profit.wing_cost)&&profit.wing_cost>=0?profit.wing_cost/profit.total_income*100:null};
}
