"use client";
import {GripVertical,MessageCircle,RotateCcw} from 'lucide-react';
import useMovable from './use-movable';
export default function FloatingCoach({onOpen}:{onOpen:()=>void}){
 const move=useMovable('rocket-desk-coach-launcher-v1',true,true);
 return <div ref={move.element} className={'floating-coach '+(move.moving?'is-moving':'')} style={move.style}>
  <button className="coach-drag-handle" {...move.handle} aria-label="운영 AI 버튼 위치 이동" title="드래그로 이동 · 방향키로 이동 · Home으로 초기화"><GripVertical size={19}/></button>
  <button className="chat-launcher" onClick={onOpen} aria-label="로켓그로스 에이전트 열기"><MessageCircle size={21}/><span>로켓그로스 에이전트</span><span className="chat-launcher-dot"/></button>
  <button className="coach-position-reset" onClick={move.reset} aria-label="운영 AI 버튼 위치 초기화" title="기본 위치로"><RotateCcw size={14}/></button>
 </div>;
}
