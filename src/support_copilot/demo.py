"""Self-contained local review interface for the authenticated drafting API."""


DEMO_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Evidence-Gated Support Copilot</title>
  <style>
    :root { color-scheme: dark; --bg:#08111f; --panel:#101c2e; --line:#26374d;
      --text:#e7eef8; --muted:#9bb0c9; --blue:#5da9ff; --green:#4dd4a7;
      --amber:#f3bf5b; --red:#ff7d8a; }
    * { box-sizing:border-box; }
    body { margin:0; font:16px/1.5 Inter,ui-sans-serif,system-ui,sans-serif;
      background:radial-gradient(circle at top left,#112846 0,var(--bg) 42%);
      color:var(--text); min-height:100vh; }
    main { width:min(980px,calc(100% - 32px)); margin:0 auto; padding:56px 0 72px; }
    .eyebrow { color:var(--green); font-weight:700; letter-spacing:.12em;
      text-transform:uppercase; font-size:12px; }
    h1 { margin:8px 0 10px; font-size:clamp(32px,6vw,58px); line-height:1.04; }
    .lede { max-width:720px; color:var(--muted); font-size:18px; }
    .panel { margin-top:30px; padding:24px; background:rgba(16,28,46,.94);
      border:1px solid var(--line); border-radius:18px; box-shadow:0 22px 60px #0005; }
    label { display:block; margin:14px 0 7px; font-size:13px; font-weight:700; color:#c7d6e8; }
    input,textarea { width:100%; border:1px solid #38506d; border-radius:10px;
      background:#091522; color:var(--text); padding:12px 14px; font:inherit; }
    textarea { min-height:132px; resize:vertical; }
    input:focus,textarea:focus { outline:2px solid #4d9eff66; border-color:var(--blue); }
    .examples { display:flex; gap:8px; flex-wrap:wrap; margin:12px 0 18px; }
    button { border:0; border-radius:10px; padding:11px 16px; font:inherit;
      font-weight:750; cursor:pointer; background:var(--blue); color:#06101e; }
    button.secondary { background:#1c2d43; color:#cfe0f4; border:1px solid #38506d;
      padding:7px 10px; font-size:13px; }
    button:disabled { opacity:.55; cursor:wait; }
    #result { display:none; margin-top:22px; }
    .status { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    .badge { border-radius:999px; padding:5px 10px; font-size:12px; font-weight:800; }
    .supported { background:#153d35; color:#75e8c3; }
    .unsupported,.uncertain { background:#4a3217; color:#ffd48a; }
    .route { background:#172f4e; color:#91c6ff; }
    .answer { margin:16px 0; padding:16px; border-left:3px solid var(--blue);
      background:#0a1625; white-space:pre-wrap; }
    .trajectory { display:flex; gap:8px; flex-wrap:wrap; margin:10px 0 18px; }
    .step { background:#17263a; color:#bdd2e9; border:1px solid #304966;
      border-radius:999px; padding:6px 10px; font:12px/1.2 ui-monospace,monospace; }
    .citation,.reason { margin:10px 0; padding:13px; background:#0a1625;
      border:1px solid var(--line); border-radius:10px; }
    .citation a { color:#8ec5ff; overflow-wrap:anywhere; }
    .citation p { color:#c4d4e7; margin:8px 0 0; }
    .reason { color:#ffd69a; }
    .notice { color:var(--muted); font-size:13px; margin-top:18px; }
    .error { color:#ff9aa4; }
  </style>
</head>
<body><main>
  <div class="eyebrow">Kubernetes reference implementation · Zero-cost demo</div>
  <h1>Evidence-Gated Support Copilot</h1>
  <p class="lede">Ask a Kubernetes-core question. The copilot cites its pinned source,
    routes uncovered tooling questions, and abstains when evidence is insufficient.</p>
  <section class="panel">
    <label for="key">Demo access key</label>
    <input id="key" type="password" autocomplete="off" placeholder="Enter the key supplied at startup">
    <label for="ticket">Support question</label>
    <textarea id="ticket" placeholder="Which Kubernetes Service type is reachable only from inside the cluster?"></textarea>
    <div class="examples">
      <button class="secondary" data-q="Which Kubernetes Service type is reachable only from within the cluster?">Core example</button>
      <button class="secondary" data-q="Why does my Helm chart fail when a values key contains a period?">Helm route</button>
      <button class="secondary" data-q="How do I configure an unrelated billing platform?">Unknown</button>
    </div>
    <button id="submit">Generate reviewed draft</button>
    <p class="notice">The optional local-overlap verifier is for a zero-cost demonstration only.
      It is not a production-qualified semantic verifier. Every response still requires review.</p>
    <p class="notice"><a href="/review">Open the private reviewer dashboard</a></p>
    <div id="result" aria-live="polite">
      <div class="status"><span id="decision" class="badge"></span><span id="route" class="badge route"></span></div>
      <div id="answer" class="answer"></div>
      <h3>Decision trajectory</h3><div id="trajectory" class="trajectory"></div>
      <h3>Citations</h3><div id="citations"></div>
      <h3>Review reasons</h3><div id="reasons"></div>
    </div>
  </section>
</main>
<script>
  const ticket = document.querySelector('#ticket');
  document.querySelectorAll('[data-q]').forEach(b => b.addEventListener('click', () => { ticket.value = b.dataset.q; }));
  const addText = (parent, tag, className, value) => { const node=document.createElement(tag); node.className=className; node.textContent=value; parent.appendChild(node); return node; };
  document.querySelector('#submit').addEventListener('click', async () => {
    const submit=document.querySelector('#submit'), result=document.querySelector('#result');
    submit.disabled=true; submit.textContent='Checking evidence…'; result.style.display='none';
    try {
      const response=await fetch('/v1/drafts',{method:'POST',headers:{'Authorization':'Bearer '+document.querySelector('#key').value,'Content-Type':'application/json'},body:JSON.stringify({ticket:ticket.value,limit:3})});
      const data=await response.json(); if(!response.ok) throw new Error(data.detail || 'Request failed');
      document.querySelector('#answer').className='answer';
      const decision=document.querySelector('#decision'); decision.textContent=data.evidence_decision; decision.className='badge '+data.evidence_decision;
      document.querySelector('#route').textContent=data.scope_route; document.querySelector('#answer').textContent=data.answer;
      const trajectory=document.querySelector('#trajectory'); trajectory.replaceChildren();
      (data.trajectory || []).forEach(step => addText(trajectory,'span','step',step));
      const citations=document.querySelector('#citations'); citations.replaceChildren();
      if(!data.citations.length) addText(citations,'div','citation','No approved citation returned.');
      data.citations.forEach(c => { const card=document.createElement('div'); card.className='citation'; addText(card,'strong','',c.title); const link=addText(card,'a','',c.source); link.href=c.source; link.target='_blank'; link.rel='noreferrer'; addText(card,'p','',c.passage); citations.appendChild(card); });
      const reasons=document.querySelector('#reasons'); reasons.replaceChildren();
      if(!data.review_reasons.length) addText(reasons,'div','reason','Mandatory human review.');
      data.review_reasons.forEach(r => addText(reasons,'div','reason',r)); result.style.display='block';
    } catch(error) { result.style.display='block'; document.querySelector('#answer').textContent=error.message; document.querySelector('#answer').className='answer error'; }
    finally { submit.disabled=false; submit.textContent='Generate reviewed draft'; }
  });
</script></body></html>"""


REVIEW_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Review Queue · Evidence-Gated Support Copilot</title>
  <style>
    :root { color-scheme:dark; --bg:#08111f; --panel:#101c2e; --line:#2a3b52;
      --text:#e7eef8; --muted:#9bb0c9; --blue:#68afff; --green:#55d8ac;
      --amber:#f3bf5b; --red:#ff8995; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; color:var(--text);
      font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif;
      background:radial-gradient(circle at top left,#112846 0,var(--bg) 42%); }
    main { width:min(1100px,calc(100% - 32px)); margin:auto; padding:44px 0 72px; }
    header { display:flex; align-items:end; justify-content:space-between; gap:24px;
      flex-wrap:wrap; }
    .eyebrow { color:var(--green); font-size:12px; font-weight:800;
      letter-spacing:.12em; text-transform:uppercase; }
    h1 { margin:6px 0; font-size:clamp(30px,5vw,48px); line-height:1.08; }
    .lede,.muted { color:var(--muted); }
    a { color:#91c7ff; }
    .auth,.card { margin-top:24px; padding:22px; border:1px solid var(--line);
      border-radius:16px; background:rgba(16,28,46,.95); box-shadow:0 18px 48px #0004; }
    .auth-row { display:grid; grid-template-columns:minmax(220px,1fr) auto auto; gap:10px; }
    label { display:block; margin:0 0 7px; color:#ccdaea; font-size:13px; font-weight:750; }
    input,textarea { width:100%; border:1px solid #3a526f; border-radius:10px;
      background:#091522; color:var(--text); padding:11px 13px; font:inherit; }
    textarea { min-height:118px; resize:vertical; }
    input:focus,textarea:focus { outline:2px solid #4d9eff66; border-color:var(--blue); }
    button { border:0; border-radius:9px; padding:10px 14px; cursor:pointer;
      background:var(--blue); color:#06101e; font:inherit; font-weight:800; }
    button.secondary { color:#d5e3f2; background:#1b2c42; border:1px solid #3a526f; }
    button.reject { background:#3d2028; color:#ffb4bc; border:1px solid #773541; }
    button:disabled { cursor:not-allowed; opacity:.5; }
    #feedback { min-height:24px; margin:12px 0 0; }
    .error { color:#ffadb5; }
    .summary { margin:24px 0 0; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    .count,.badge,.step { padding:5px 9px; border-radius:999px; font-size:12px; font-weight:800; }
    .count,.route { background:#183353; color:#a5d2ff; }
    .pending,.uncertain,.unsupported { background:#4a3217; color:#ffd48a; }
    .approved,.supported { background:#153d35; color:#75e8c3; }
    .rejected { background:#49242b; color:#ffb4bc; }
    .card-head { display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; }
    .card h2 { margin:0; font-size:20px; }
    .badges,.trajectory,.actions { display:flex; gap:8px; flex-wrap:wrap; }
    .ticket,.evidence { margin:16px 0; padding:14px; border-radius:10px;
      border:1px solid var(--line); background:#0a1625; white-space:pre-wrap; }
    .step { background:#17263a; color:#bdd2e9; border:1px solid #304966;
      font:12px/1.2 ui-monospace,monospace; }
    .reasons { color:#ffd69a; }
    .citation { margin-top:10px; padding-top:10px; border-top:1px solid var(--line); }
    .citation p { margin:6px 0 0; color:#c4d4e7; }
    .actions { margin-top:12px; }
    .empty { margin-top:24px; padding:30px; border:1px dashed #3a526f;
      border-radius:14px; color:var(--muted); text-align:center; }
    @media (max-width:620px) { .auth-row { grid-template-columns:1fr; } }
  </style>
</head>
<body><main>
  <header>
    <div><div class="eyebrow">Private operations surface · Review only</div>
      <h1>GitHub review queue</h1>
      <div class="lede">Inspect evidence, edit drafts, and record a human decision.
        Decisions never post to GitHub.</div></div>
    <a href="/">Public drafting demo</a>
  </header>
  <section class="auth" aria-labelledby="access-title">
    <label id="access-title" for="review-key">Private reviewer key</label>
    <div class="auth-row">
      <input id="review-key" type="password" autocomplete="off"
        placeholder="Key remains in this page only">
      <button id="load">Load review queue</button>
      <button id="lock" class="secondary" disabled>Lock dashboard</button>
    </div>
    <div id="feedback" class="muted" role="status" aria-live="polite">Not authenticated.</div>
  </section>
  <div id="summary" class="summary" hidden></div>
  <div id="reviews"></div>
</main>
<script>
  const keyInput=document.querySelector('#review-key');
  const feedback=document.querySelector('#feedback');
  const reviewsNode=document.querySelector('#reviews');
  const summary=document.querySelector('#summary');
  const loadButton=document.querySelector('#load');
  const lockButton=document.querySelector('#lock');
  const text=(parent,tag,className,value)=>{const node=document.createElement(tag);
    node.className=className;node.textContent=value;parent.appendChild(node);return node;};
  const safeUrl=value=>{try{const url=new URL(value);return url.protocol==='https:'?url.href:null;}catch{return null;}};
  const request=async(path,options={})=>{const response=await fetch(path,{...options,headers:{
    ...(options.headers||{}),'Authorization':'Bearer '+keyInput.value}});
    let data;try{data=await response.json();}catch{data={};}
    if(!response.ok)throw new Error(response.status===401?'Invalid reviewer key.':(data.detail||'Request failed.'));
    return data;};
  const badge=(parent,value)=>text(parent,'span','badge '+value,value);
  function renderReview(item){
    const card=document.createElement('article');card.className='card';
    const head=text(card,'div','card-head','');
    const title=text(head,'div','','');
    const issueLink=text(title,'a','',item.repository+' #'+item.issue_number);
    const issueUrl=safeUrl(item.issue_url);if(issueUrl){issueLink.href=issueUrl;issueLink.target='_blank';issueLink.rel='noreferrer';}
    text(title,'h2','',item.status==='pending'?'Pending review':'Reviewed item');
    const badges=text(head,'div','badges','');badge(badges,item.status);badge(badges,item.evidence_decision);
    text(badges,'span','badge route',item.scope_route);
    text(card,'div','ticket',item.ticket);
    const trajectory=text(card,'div','trajectory','');
    (item.trajectory||[]).forEach(value=>text(trajectory,'span','step',value));
    if((item.review_reasons||[]).length){const reasons=text(card,'div','evidence reasons','');
      item.review_reasons.forEach(value=>text(reasons,'div','',value));}
    if((item.citations||[]).length){const evidence=text(card,'div','evidence','');
      text(evidence,'strong','','Approved evidence');item.citations.forEach(citation=>{
        const row=text(evidence,'div','citation','');const link=text(row,'a','',citation.title);
        const source=safeUrl(citation.source);if(source){link.href=source;link.target='_blank';link.rel='noreferrer';}
        text(row,'p','',citation.passage);});}
    const answerLabel=text(card,'label','','Final reviewed answer');
    const answer=document.createElement('textarea');answer.value=item.final_answer||item.answer||'';
    answer.id='answer-'+item.review_id;answerLabel.htmlFor=answer.id;answer.disabled=item.status!=='pending';card.appendChild(answer);
    if(item.status==='pending'){
      const actions=text(card,'div','actions','');const approve=text(actions,'button','approve','Approve decision');
      const reject=text(actions,'button','reject','Reject decision');
      const decide=async action=>{if(!confirm('Record this '+action+' decision? This will not post to GitHub.'))return;
        approve.disabled=true;reject.disabled=true;feedback.className='muted';feedback.textContent='Recording decision…';
        try{await request('/v1/reviews/'+encodeURIComponent(item.review_id),{method:'PATCH',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({action,edited_answer:action==='approve'?answer.value:null})});await loadReviews();}
        catch(error){feedback.className='error';feedback.textContent=error.message;approve.disabled=false;reject.disabled=false;}};
      approve.addEventListener('click',()=>decide('approve'));reject.addEventListener('click',()=>decide('reject'));
    }
    return card;
  }
  async function loadReviews(){loadButton.disabled=true;feedback.className='muted';feedback.textContent='Loading private queue…';
    try{const items=await request('/v1/reviews');reviewsNode.replaceChildren();summary.replaceChildren();summary.hidden=false;
      const pending=items.filter(item=>item.status==='pending').length;text(summary,'span','count',pending+' pending');
      text(summary,'span','muted',items.length+' total · posting disabled');
      if(!items.length)text(reviewsNode,'div','empty','No reviews are currently queued.');
      items.forEach(item=>reviewsNode.appendChild(renderReview(item)));
      lockButton.disabled=false;feedback.textContent='Authenticated. Queue loaded securely.';}
    catch(error){reviewsNode.replaceChildren();summary.hidden=true;feedback.className='error';feedback.textContent=error.message;}
    finally{loadButton.disabled=false;}}
  loadButton.addEventListener('click',loadReviews);
  lockButton.addEventListener('click',()=>{keyInput.value='';reviewsNode.replaceChildren();
    summary.replaceChildren();summary.hidden=true;lockButton.disabled=true;feedback.className='muted';
    feedback.textContent='Dashboard locked. Reviewer key cleared.';keyInput.focus();});
  keyInput.addEventListener('keydown',event=>{if(event.key==='Enter')loadReviews();});
</script></body></html>"""
