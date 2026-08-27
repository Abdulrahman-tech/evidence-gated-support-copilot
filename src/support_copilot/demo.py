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
  <div class="eyebrow">Kubernetes reference implementation · Local demo</div>
  <h1>Evidence-Gated Support Copilot</h1>
  <p class="lede">Ask a Kubernetes-core question. The copilot cites its pinned source,
    routes uncovered tooling questions, and abstains when evidence is insufficient.</p>
  <section class="panel">
    <label for="key">Local API key</label>
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
