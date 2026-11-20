import {reviews, flowEvents} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {ReviewStatus, FlowEventType} from '../constants/enums.js';
import {esc, date, fmt, notify, toEpoch, toLocalInput} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

const ZONES = ['全部', '星空厅', '水世界', '机械坊'];
let timer = null;

function reviewStatus(v){return '<span class="status '+esc(v)+'">'+esc(ReviewStatus[v]||v)+'</span>';}

function conclusionCard(title, eyebrow, c){
 if(!c)return '<section class="panel empty">'+esc(title)+'：等待核验完成。</section>';
 const zoneRows=(c.by_zone||[]).map(z=>'<div class="zone-chip"><span>'+esc(z.zone)+'</span><strong>'+esc(fmt(z.visitors))+'</strong></div>').join('');
 return '<section class="panel conclusion"><div class="section-title"><h2>'+esc(title)+'</h2><span>'+esc(eyebrow)+'</span></div>'+
  '<p class="cutoff-line">收讫时点 '+esc(date(c.cutoff))+' · 营业日 '+esc(c.business_date)+' · 展区 '+esc(c.zone)+'</p>'+
  '<div class="metrics"><div><span>有效记录</span><strong>'+esc(fmt(c.active_records))+'</strong></div><div><span>进区客流合计</span><strong>'+esc(fmt(c.visitors))+'<small>人</small></strong></div></div>'+
  '<div class="zone-chips">'+(zoneRows||'<span class="hint">该口径下无分区数据</span>')+'</div></section>';
}

function differencePanel(d){
 if(!d)return '';
 const cols=[{key:'flow_no',label:'记录号'},{key:'then',label:'当时'},{key:'now',label:'今天'},{key:'reasons',label:'差异原因'},{key:'delta_visitors',label:'客流变动'}];
 const rows=(d.details||[]).map(x=>({
  flow_no:x.flow_no,
  then:x.then?x.then.business_date+' · '+fmt(x.then.visitors)+' 人':'— 不在范围 —',
  now:x.now?x.now.business_date+' · '+fmt(x.now.visitors)+' 人':'— 已移除 —',
  reasons:x.reasons.join('；'),
  delta_visitors:(x.delta_visitors>0?'+':'')+fmt(x.delta_visitors)
 }));
 return '<section class="panel"><div class="section-title"><h2>造成差异的同号记录</h2><span>'+esc(d.changed_records)+' 条 · 客流净变动 '+(d.visitors_delta>0?'+':'')+esc(fmt(d.visitors_delta))+' 人</span></div>'+
  table(cols,rows,'两次核验口径一致，没有发现差异记录。')+'</section>';
}

function detailPanel(r){
 const res=r.result||{};
 if(r.status==='failed')return '<section class="panel empty">核验中断：'+esc(r.error||'未知错误')+'。可点击“断点续算”，不另开复盘、不换样本。</section>';
 if(r.status!=='completed'){
  const pct=Math.round((r.progress||0)*100);
  return '<section class="panel"><div class="section-title"><h2>核验进度</h2><span>'+reviewStatus(r.status)+'</span></div>'+
   '<div class="progress"><div style="width:'+pct+'%"></div></div><p class="hint">已处理样本 '+esc(r.cursor)+' / '+esc(r.sample_size)+'（'+pct+'%）。中断后从该断点续算，重试沿用同一复盘与同一样本。</p></section>';
 }
 return '<div class="two-columns">'+conclusionCard('当时所知的客流','AS OF THEN · 选定过去时点',res.then)+conclusionCard('今天所知的客流','AS OF NOW · 创建时冻结',res.now)+'</div>'+
  '<section class="panel result-lead"><p class="eyebrow">两次结论对照</p><h2>当时 '+esc(fmt(res.then.visitors))+' 人 → 今天 '+esc(fmt(res.now.visitors))+
  ' 人，净变动 '+(res.difference.visitors_delta>0?'+':'')+esc(fmt(res.difference.visitors_delta))+' 人，涉及 '+esc(res.difference.changed_records)+' 条同号记录。</h2></section>'+
  differencePanel(res.difference);
}

function ledger(events){
 const cols=[{key:'received_at',label:'实际收讫'},{key:'flow_no',label:'记录号'},{key:'zone',label:'展区'},{key:'business_date',label:'归属营业日'},{key:'event_type',label:'类型'},{key:'visitors',label:'进区'},{key:'note',label:'备注'}];
 const rows=events.map(e=>({received_at:date(e.received_at),flow_no:e.flow_no,zone:e.zone,business_date:e.business_date,event_type:FlowEventType[e.event_type]||e.event_type,visitors:e.visitors,note:e.note||''}));
 return '<section class="panel"><div class="section-title"><h2>客流收讫台账（双时间）</h2><span>'+events.length+' 条事件 · 只追加不覆盖</span></div>'+
  table(cols,rows,'暂无客流事件。')+'</section>';
}

export async function reviewsPage(id){
 const [list,events]=await Promise.all([reviews.list(),flowEvents.list()]);
 workspace.reviews=list; workspace.flowEvents=events;
 const r=id?await reviews.get(id):(list[0]||null);
 if(r&&!list.some(x=>x.id===r.id))list.push(r);
 const canWrite=session.user.role!=='viewer';
 // 默认对齐演示台账：2026-11-06 午间盘点；若该时点已非过去则回退到 24 小时前。
 const seedThen=Date.parse('2026-11-06T12:00:00')/1000;
 const defaultThen=toLocalInput(seedThen<Date.now()/1000?seedThen:Date.now()/1000-86400);
 return heading('06 / BITEMPORAL REVIEW','导览试点复盘','选营业日与一个过去收讫时点，分别核验“当时所知”与“今天所知”的客流。补报、更正、撤销均按实际收讫时间入账，样本在创建瞬间圈定，并发补报不会侵入。','<button class="button" id="refresh-reviews">刷新 ↻</button>')+
  '<div class="report-grid"><section class="panel"><div class="section-title"><h2>发起复盘</h2></div><form id="review-form">'+
  '<label>复盘名称<input name="name" required minlength="2" value="导览试点复盘"></label>'+
  '<label>营业日<input name="business_date" type="date" required value="2026-11-06"></label>'+
  '<label>展区<select name="zone">'+ZONES.map(z=>'<option value="'+esc(z)+'">'+esc(z)+'</option>').join('')+'</select></label>'+
  '<label>“当时”收讫时点（过去）<input name="as_of_then" type="datetime-local" required value="'+esc(defaultThen)+'"></label>'+
  '<p class="hint">“今天”时点在提交瞬间由服务端冻结；样本仅含此时点前已收讫事件。</p>'+
  '<button type="submit" class="primary" '+(canWrite?'':'disabled')+'>圈定样本并核验 ↗</button></form>'+
  '<div class="section-title" style="margin-top:30px"><h2>登记收讫事件</h2></div><form id="flow-form">'+
  '<div class="parameter-grid"><label>记录号<input name="flow_no" required placeholder="F-1006"></label><label>展区<select name="zone">'+ZONES.filter(z=>z!=='全部').map(z=>'<option>'+esc(z)+'</option>').join('')+'</select></label></div>'+
  '<div class="parameter-grid"><label>归属营业日<input name="business_date" type="date" required value="2026-11-06"></label><label>类型<select name="event_type">'+Object.entries(FlowEventType).map(([k,v])=>'<option value="'+k+'">'+esc(v)+'</option>').join('')+'</select></label></div>'+
  '<div class="parameter-grid"><label>进区人数<input name="visitors" type="number" min="0" step="1" required value="0"></label><label>实际收讫时间<input name="received_at" type="datetime-local" required value="'+esc(toLocalInput(Date.now()/1000))+'"></label></div>'+
  '<label>备注<input name="note" placeholder="可选"></label>'+
  '<button type="submit" class="primary" '+(canWrite?'':'disabled')+'>登记事件</button></form>'+
  (canWrite?'':'<p class="hint">观察员只读，无法登记或发起复盘。</p>')+'</section>'+
  '<section><div class="section-title"><h2>复盘记录</h2><span>'+list.length+' 次</span></div><div class="schedule-list">'+
   list.map(x=>'<article class="'+(r&&r.id===x.id?'active-review':'')+'"><div><strong>'+esc(x.name)+'</strong><p>'+esc(x.business_date)+' · '+esc(x.zone)+' · 样本 '+esc(x.sample_size)+'</p><small>'+reviewStatus(x.status)+' '+Math.round((x.progress||0)*100)+'%</small></div>'+
    '<div><a class="button small" href="#/reviews/'+x.id+'">查看</a>'+(canWrite&&x.status!=='completed'?' <button class="button small" data-retry="'+x.id+'">断点续算</button>':'')+'</div></article>').join('')+
   (!list.length?'<p class="empty">尚无复盘。先在左侧圈定一次样本。</p>':'')+'</div>'+
  (r?detailPanel(r):'')+'</section></div>'+ledger(events);
}

export function bindReviews(refresh){
 clearInterval(timer);
 document.querySelector('#refresh-reviews').onclick=refresh;
 submit(document.querySelector('#review-form'),async f=>{
  const then=toEpoch(f.get('as_of_then'));
  const created=await reviews.create({name:f.get('name'),business_date:f.get('business_date'),zone:f.get('zone'),as_of_then:then});
  notify('复盘已创建，样本 '+created.sample_size+' 条已圈定');
  location.hash='#/reviews/'+created.id;
 });
 submit(document.querySelector('#flow-form'),async f=>{
  await flowEvents.create({flow_no:f.get('flow_no'),zone:f.get('zone'),business_date:f.get('business_date'),event_type:f.get('event_type'),visitors:Number(f.get('visitors')),received_at:toEpoch(f.get('received_at')),note:f.get('note')||''});
  notify('收讫事件已登记'); await refresh();
 });
 document.querySelectorAll('[data-retry]').forEach(b=>b.onclick=async()=>{try{await reviews.retry(b.dataset.retry);notify('已重新入队，将从断点续算');await refresh();}catch(e){notify(e.message,true);}});
 // 运行中的复盘自动轮询，展示进度推进；完成、失败或离开本页后停止。
 const active=document.querySelector('.status.running,.status.queued');
 if(active){timer=setInterval(async()=>{
  if(!location.hash.startsWith('#/reviews')){clearInterval(timer);return;}
  const sel=location.hash.split('/')[2];
  if(sel){const cur=await reviews.get(Number(sel));if(cur.status==='completed'||cur.status==='failed'){clearInterval(timer);}await refresh();}
 },1500);}
}
