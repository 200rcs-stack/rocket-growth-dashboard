"use client";
import {useCallback,useEffect,useRef,useState} from 'react';
import type {CSSProperties,KeyboardEvent,PointerEvent} from 'react';
import {clampFloating,floatingBounds,savedFloating,type Point} from '../lib/floating-position';
export default function useMovable(key:string,active=true,launcher=false){
 const element=useRef<HTMLDivElement>(null),current=useRef<Point|null>(null),drag=useRef<{id:number;start:Point;base:Point}|null>(null);
 const [position,setPosition]=useState<Point|null>(null),[moving,setMoving]=useState(false);
 const bounds=useCallback(()=>{const rect=element.current?.getBoundingClientRect();return floatingBounds(rect?.width??0,rect?.height??0,window.innerWidth,window.innerHeight)},[]);
 const update=useCallback((next:Point,persist=false)=>{const b=bounds(),p=clampFloating(next,b);current.current=p;setPosition(p);if(persist){try{localStorage.setItem(key,JSON.stringify({x:b.maxX>12?(p.x-12)/(b.maxX-12):0,y:b.maxY>12?(p.y-12)/(b.maxY-12):0}))}catch{}}},[bounds,key]);
 const reset=useCallback(()=>{const b=bounds();update({x:b.maxX-18,y:launcher?b.maxY-74:12});try{localStorage.removeItem(key)}catch{}},[bounds,key,launcher,update]);
 useEffect(()=>{if(!active)return;const initialize=()=>{if(!element.current)return;let saved=null;try{saved=savedFloating(JSON.parse(localStorage.getItem(key)||'null'),bounds())}catch{}if(saved)update(saved);else reset();};const frame=requestAnimationFrame(initialize);const resize=()=>{if(current.current)update(current.current,true)};window.addEventListener('resize',resize);return()=>{cancelAnimationFrame(frame);window.removeEventListener('resize',resize);drag.current=null;setMoving(false)}},[active,key,bounds,update,reset]);
 const onPointerDown=(event:PointerEvent<HTMLButtonElement>)=>{if(event.button!==0||!element.current)return;event.preventDefault();const rect=element.current.getBoundingClientRect();drag.current={id:event.pointerId,start:{x:event.clientX,y:event.clientY},base:{x:rect.left,y:rect.top}};event.currentTarget.setPointerCapture(event.pointerId);setMoving(true)};
 const onPointerMove=(event:PointerEvent<HTMLButtonElement>)=>{const d=drag.current;if(!d||d.id!==event.pointerId)return;update({x:d.base.x+event.clientX-d.start.x,y:d.base.y+event.clientY-d.start.y})};
 const finish=(event:PointerEvent<HTMLButtonElement>)=>{if(drag.current?.id!==event.pointerId)return;drag.current=null;setMoving(false);if(current.current)update(current.current,true);if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId)};
 const onKeyDown=(event:KeyboardEvent<HTMLButtonElement>)=>{if(event.key==='Home'){event.preventDefault();reset();return;}const step=event.shiftKey?40:10,change:Record<string,Point>={ArrowLeft:{x:-step,y:0},ArrowRight:{x:step,y:0},ArrowUp:{x:0,y:-step},ArrowDown:{x:0,y:step}};if(!change[event.key]||!element.current)return;event.preventDefault();const rect=element.current.getBoundingClientRect(),d=change[event.key];update({x:rect.left+d.x,y:rect.top+d.y},true)};
 const style:CSSProperties=position?{left:position.x,top:position.y,right:'auto',bottom:'auto'}:{};
 return {element,style,moving,reset,handle:{onPointerDown,onPointerMove,onPointerUp:finish,onPointerCancel:finish,onKeyDown}};
}
