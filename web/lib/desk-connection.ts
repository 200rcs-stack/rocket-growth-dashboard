export type ConnectionKind='auth'|'forbidden'|'timeout'|'network'|'server';
export class DeskConnectionError extends Error{constructor(public kind:ConnectionKind,message:string){super(message)}}
export async function readDesk(fetcher:typeof fetch=fetch){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
 try{
  const response=await fetcher('/api/desk',{cache:'no-store',credentials:'same-origin',signal:controller.signal});
  if(response.status===401||response.redirected||response.headers.get('content-type')?.includes('text/html'))throw new DeskConnectionError('auth','이 브라우저의 로그인을 확인해 주세요. 다른 PC의 접속을 종료할 필요는 없습니다.');
  if(response.status===403)throw new DeskConnectionError('forbidden','이 사이트를 만든 ChatGPT 계정으로 로그인해 주세요. PC가 아니라 계정의 접근 권한을 확인합니다.');
  if(!response.ok)throw new DeskConnectionError('server','웹 저장소가 응답하지 못했습니다. 잠시 후 다시 연결해 주세요.');
  return await response.json();
 }catch(error){if(error instanceof DeskConnectionError)throw error;throw new DeskConnectionError(controller.signal.aborted?'timeout':'network',controller.signal.aborted?'자료 연결 응답이 지연됐습니다. 다른 PC와 상관없이 다시 연결할 수 있습니다.':'네트워크 연결을 확인해 주세요. 이전 화면은 유지됩니다.')}finally{clearTimeout(timer)}
}
