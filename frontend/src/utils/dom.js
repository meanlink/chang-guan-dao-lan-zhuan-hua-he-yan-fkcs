export const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const fmt=v=>typeof v==='number'?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:4}).format(v):String(v??'—');
export const date=v=>new Date(v*1000).toLocaleString('zh-CN',{hour12:false});
// datetime-local 控件值（本地时间，无秒）与后端 epoch 秒互转。
export const toEpoch=value=>value?Math.floor(new Date(value).getTime()/1000):null;
export const toLocalInput=epoch=>{if(epoch==null)return'';const d=new Date(epoch*1000),p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes());};
export function notify(message,error=false){const t=document.querySelector('#toast');t.textContent=message;t.className=error?'show error':'show';setTimeout(()=>t.className='',5000);}
