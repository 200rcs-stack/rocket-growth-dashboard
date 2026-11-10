export type Point={x:number;y:number};
export function floatingBounds(width:number,height:number,viewportWidth:number,viewportHeight:number){return {maxX:Math.max(12,viewportWidth-width-12),maxY:Math.max(12,viewportHeight-height-12)}}
export function clampFloating(point:Point,bounds:{maxX:number;maxY:number}):Point{return {x:Math.min(bounds.maxX,Math.max(12,Number.isFinite(point.x)?point.x:12)),y:Math.min(bounds.maxY,Math.max(12,Number.isFinite(point.y)?point.y:12))}}
export function savedFloating(value:unknown,bounds:{maxX:number;maxY:number}):Point|null{
 if(!value||typeof value!=='object')return null;const p=value as Point;
 if(!Number.isFinite(p.x)||!Number.isFinite(p.y)||p.x<0||p.x>1||p.y<0||p.y>1)return null;
 return clampFloating({x:12+p.x*(bounds.maxX-12),y:12+p.y*(bounds.maxY-12)},bounds);
}
