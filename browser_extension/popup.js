document.getElementById('save').addEventListener('click',async()=>{
 const token=document.getElementById('token').value.trim();
 if(token.length<30){document.getElementById('status').textContent='연결 코드를 확인해 주세요.';return;}
 await chrome.storage.local.set({token,enabled:true});
 await chrome.runtime.sendMessage({type:'poll'});
 document.getElementById('token').value='';
 document.getElementById('status').textContent='연결 요청을 보냈습니다. 대시보드에서 연결 상태를 확인하세요.';
});
document.getElementById('stop').addEventListener('click',async()=>{
 await chrome.storage.local.remove(['token']);await chrome.storage.local.set({enabled:false});
 document.getElementById('status').textContent='연결을 해제했습니다.';
});
