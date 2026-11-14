// State
let currentRunId = null;
let currentDraftId = null;
let eventSource = null;
let timerInterval = null;
let runStartTime = null;
let highestEventId = 0;

// Tab Switching
document.querySelectorAll('.nav-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    if (tab.tagName === 'A' && tab.getAttribute('href')) {
      return; // allow normal page navigation
    }
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    const target = tab.getAttribute('data-tab');
    if (target) {
      const pane = document.getElementById(`tab-${target}`);
      if (pane) pane.classList.add('active');
      if (target === 'dashboard') loadDashboard();
      if (target === 'assumptions') loadAssumptions();
    }
  });
});

// Quick fill input
function fillInput(name, site, role = '', recipName = '') {
  if (document.getElementById('company_name')) {
    document.getElementById('company_name').value = name;
  }
  if (document.getElementById('website_hint')) {
    document.getElementById('website_hint').value = site || '';
  }
  if (document.getElementById('recipient_role')) {
    document.getElementById('recipient_role').value = role || '';
  }
  if (document.getElementById('recipient_name')) {
    document.getElementById('recipient_name').value = recipName || '';
  }
}

function fillPersonInput(name, comp, city) {
  if (document.getElementById('person_name')) {
    document.getElementById('person_name').value = name;
  }
  // The unified form uses the company field as the visible employer clue.
  if (document.getElementById('company_name') && comp) {
    document.getElementById('company_name').value = comp;
  }
  if (document.getElementById('company_hint')) {
    document.getElementById('company_hint').value = comp || '';
  }
  if (document.getElementById('city_hint')) {
    document.getElementById('city_hint').value = city || '';
  }
  updateRunModePreview();
}

function loadDemoCase(caseId) {
  window.currentDemoCase = caseId;
  const cacheCheckbox = document.getElementById('use_cache_checkbox');
  if (cacheCheckbox) {
    cacheCheckbox.checked = true;
    updateCacheIndicator();
  }
  const cases = {
    ramp_company: { company: 'Ramp', person: '' },
    ramp_role: { company: 'Ramp', role: 'CFO' },
    person_only: { person: 'Immad Akhund' },
    ramp_person: { company: 'Ramp', person: 'Eric Glyman', role: 'Co-founder and Co-CEO' },
    mercury_ambiguous: { company: 'Mercury' },
    mercury_qualified: { company: 'Mercury (Finance)' },
    mercury_person: { company: 'Mercury', person: 'Immad Akhund', role: 'Co-founder and CEO' },
    ambiguous_person: { person: 'Alex Smith' },
    drishti_matiks: { person: 'Drishti Pandita' },
    sudhanshu_matiks: { person: 'Sudhanshu Bhatia' },
    matiks_community: { person: 'Drishti Pandita' },
    flexport_employee: { company: 'Flexport', site: 'flexport.com', country: 'United States', industry: 'Supply Chain & Freight Logistics' },
    mahalaxmi_employee: { company: 'Flexport', site: 'flexport.com', country: 'United States', industry: 'Supply Chain & Freight Logistics' },
    pedro_brex: { company: 'Brex', person: 'Pedro Franceschi', role: 'Co-founder and CEO', site: 'brex.com', industry: 'FinTech / Corporate Card' },
    brex_compliance: { company: 'Brex', person: 'Pedro Franceschi', role: 'Co-founder and CEO', site: 'brex.com', industry: 'FinTech / Corporate Card' },
    shipbob_changelog: { company: 'ShipBob', site: 'shipbob.com', industry: 'E-commerce Fulfillment & Logistics' }
  }[caseId];
  if (!cases) return;
  const values = {
    company_name: cases.company,
    website_hint: cases.site,
    person_name: cases.person,
    recipient_role: cases.role,
    industry_hint: cases.industry,
    country_hint: cases.country,
    city_hint: cases.location,
    linkedin_hint: cases.linkedin
  };
  Object.entries(values).forEach(([id, value]) => {
    const field = document.getElementById(id);
    if (!field) return;
    field.value = value || '';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    field.dispatchEvent(new Event('change', { bubbles: true }));
  });
  const hintsPanel = document.querySelector('.hints-accordion');
  if (hintsPanel) hintsPanel.open = false;
  updateRunModePreview();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

document.querySelector('.demo-case-grid')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-demo-case]');
  if (button) loadDemoCase(button.dataset.demoCase);
});

function updateCacheIndicator() {
  const checkbox = document.getElementById('use_cache_checkbox');
  const indicator = document.getElementById('cache-mode-indicator');
  if (!checkbox || !indicator) return;
  if (checkbox.checked) {
    indicator.textContent = '⚡ Cached Replay Active';
    indicator.className = 'cache-mode-badge cached';
  } else {
    indicator.textContent = '🌐 Fresh Live Run';
    indicator.className = 'cache-mode-badge fresh';
  }
}

document.getElementById('use_cache_checkbox')?.addEventListener('change', updateCacheIndicator);

function updateRunModePreview() {
  const company = document.getElementById('company_name')?.value.trim() || '';
  const person = document.getElementById('person_name')?.value.trim() || '';
  const role = document.getElementById('recipient_role')?.value.trim() || '';
  const titleEl = document.getElementById('run-mode-title');
  const descriptionEl = document.getElementById('run-mode-description');
  const badgeEl = document.getElementById('run-mode-badge');
  if (!titleEl || !descriptionEl || !badgeEl) return;

  if (person) {
    titleEl.textContent = role ? 'Person-first research with role context' : 'Person-first research';
    descriptionEl.textContent = role
      ? `We'll research ${person}, use ${role} to guide the opportunity framing, and tailor the draft for that role.`
      : company
        ? `We'll start with ${person}, using ${company} as an employer clue while we resolve their profile.`
        : `We'll identify ${person}'s employer and role, then build outreach around the person.`;
    badgeEl.textContent = role ? 'Person + role' : 'Person-first';
  } else if (company) {
    titleEl.textContent = role ? 'Company research with role context' : 'Company-level research';
    descriptionEl.textContent = role
      ? `We'll research ${company}'s opportunities and shape the draft for a ${role}.`
      : `We'll research ${company} and surface grounded operational opportunities.`;
    badgeEl.textContent = role ? 'Company + role' : 'Company';
  } else {
    titleEl.textContent = 'Choose a company or person';
    descriptionEl.textContent = 'A role adds context to the draft. Start with a company name or a person to begin research.';
    badgeEl.textContent = role ? 'Role adds context' : 'Ready when you are';
  }
}

['company_name', 'person_name', 'recipient_role'].forEach((id) => {
  document.getElementById(id)?.addEventListener('input', updateRunModePreview);
});
updateRunModePreview();

// Preflight Check on load
async function checkPreflight() {
  const groqDot = document.getElementById('groq-dot');
  const groqStatus = document.getElementById('groq-status');
  const geminiDot = document.getElementById('gemini-dot');
  const geminiStatus = document.getElementById('gemini-status');

  try {
    const res = await fetch('/api/preflight');
    const data = await res.json();

    if (data.groq) {
      if (data.groq.status === 'ok') {
        groqDot?.classList.remove('warning', 'error');
        groqDot?.classList.add('ready');
        if (groqStatus) groqStatus.textContent = `Online (${data.groq.latency_ms}ms)`;
      } else {
        groqDot?.classList.remove('ready', 'warning');
        groqDot?.classList.add('error');
        if (groqStatus) groqStatus.textContent = 'Degraded';
      }
    } else {
      if (groqStatus) groqStatus.textContent = 'Unconfigured';
    }

    if (data.gemini) {
      if (data.gemini.status === 'ok') {
        geminiDot?.classList.remove('warning', 'error');
        geminiDot?.classList.add('ready');
        if (geminiStatus) geminiStatus.textContent = `Online (${data.gemini.latency_ms}ms)`;
      } else {
        geminiDot?.classList.remove('ready', 'warning');
        geminiDot?.classList.add('error');
        if (geminiStatus) geminiStatus.textContent = 'Degraded';
      }
    } else {
      if (geminiStatus) geminiStatus.textContent = 'Unconfigured';
    }
  } catch (e) {
    if (groqStatus) groqStatus.textContent = 'Offline';
    if (geminiStatus) geminiStatus.textContent = 'Offline';
  }
}
checkPreflight();

function handleKeyRotationEvent(payload) {
  if (!payload || !payload.provider) return;
  const prov = payload.provider.toLowerCase();
  const chip = document.getElementById(`provider-${prov}`);
  const dot = document.getElementById(`${prov}-dot`);
  const status = document.getElementById(`${prov}-status`);

  if (chip && dot && status) {
    chip.classList.add('warning-active');
    dot.className = 'status-dot warning pulse';
    const reasonTag = payload.status_code === 503 ? '503 High Demand' : '429 Rate Limit';
    status.textContent = `Key #${payload.failed_key_index} (${reasonTag}) ➔ #${payload.next_key_index}`;
  }
}

function handleProviderSuccess(providerName, keyIndex) {
  const prov = (providerName || '').toLowerCase();
  const chip = document.getElementById(`provider-${prov}`);
  const dot = document.getElementById(`${prov}-dot`);
  const status = document.getElementById(`${prov}-status`);

  if (chip && dot && status) {
    chip.classList.remove('warning-active');
    dot.className = 'status-dot ready';
    status.textContent = keyIndex ? `Key #${keyIndex} Active` : 'Online';
  }
}

// Timer helpers
function startTimer() {
  stopTimer();
  runStartTime = Date.now();
  timerInterval = setInterval(() => {
    const elapsed = ((Date.now() - runStartTime) / 1000).toFixed(1);
    const el = document.getElementById('live-timer');
    if (el) el.textContent = `${elapsed}s`;
  }, 100);
}

function stopTimer() {
  if (timerInterval) clearInterval(timerInterval);
}

// Stepper Helper
function getStageOrder() {
  return document.getElementById('step-s0')
    ? ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7']
    : ['s1', 's2', 's3', 's4', 's5', 's6', 's7'];
}

function setStepperStage(stageKey, isCompleted = false) {
  const normKey = stageKey.split('_')[0]; // e.g. s1_resolve -> s1, s0_person -> s0
  const stageOrder = getStageOrder();
  const idx = stageOrder.indexOf(normKey);
  if (idx === -1) return;

  const agentNames = {
    s0: 'Prospect Resolver (S0)',
    s1: 'Entity Resolver (S1)',
    s2: 'Research Swarm (S2)',
    s3: 'Problem Miner (S3)',
    s4: 'Ranker & Role-Fit (S4)',
    s5: 'Solution Architect (S5)',
    s6: 'Outreach Drafter (S6)',
    s7: 'Grounding Guard (S7)'
  };
  const activeAgentEl = document.getElementById('active-agent-pill');
  if (activeAgentEl) {
    if (isCompleted && normKey === 's7') {
      activeAgentEl.textContent = 'Agent: All Stages Done';
      activeAgentEl.style.color = '#34d399';
    } else {
      activeAgentEl.textContent = `Agent: ${agentNames[normKey] || normKey.toUpperCase()}`;
      activeAgentEl.style.color = '#38bdf8';
    }
  }

  ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7'].forEach((s) => {
    const badge = document.getElementById(`pagent-${s}`);
    const i = stageOrder.indexOf(s);
    if (badge) {
      const statusEl = badge.querySelector('.pagent-status');
      if (i !== -1 && (i < idx || (i === idx && isCompleted))) {
        badge.className = 'pipeline-agent-badge completed';
        if (statusEl) statusEl.textContent = 'Completed';
      } else if (i === idx) {
        badge.className = 'pipeline-agent-badge active';
        if (statusEl) statusEl.textContent = 'Working...';
      } else {
        badge.className = 'pipeline-agent-badge';
        if (statusEl) statusEl.textContent = 'Ready';
      }
    }
  });

  stageOrder.forEach((s, i) => {
    const node = document.getElementById(`step-${s}`);
    if (!node) return;
    if (i < idx || (i === idx && isCompleted)) {
      node.className = 'step-node completed';
    } else if (i === idx) {
      node.className = 'step-node active';
    } else {
      node.className = 'step-node';
    }
  });
}

// Form Submission
const launchFormEl = document.getElementById('launch-form');
if (launchFormEl) {
  launchFormEl.addEventListener('submit', async (e) => {
    e.preventDefault();
    const personNameEl = document.getElementById('person_name');
    const companyNameEl = document.getElementById('company_name');
    const personName = personNameEl ? personNameEl.value.trim() : null;
    const companyName = companyNameEl ? companyNameEl.value.trim() : (personName ? `Prospect: ${personName}` : '');
    if (!companyName && !personName) {
      const feedback = document.getElementById('launch-form-feedback');
      if (feedback) feedback.textContent = 'Enter a company or person to start research.';
      (companyNameEl || personNameEl)?.focus();
      return;
    }
    const feedback = document.getElementById('launch-form-feedback');
    if (feedback) feedback.textContent = '';

    const useCache = document.getElementById('use_cache_checkbox') ? document.getElementById('use_cache_checkbox').checked : true;
    const payload = {
      person_name: personName,
      company_name: companyName,
      company_hint: document.getElementById('company_hint') ? document.getElementById('company_hint').value.trim() || null : null,
      city_hint: document.getElementById('city_hint') ? document.getElementById('city_hint').value.trim() || null : null,
      role_hint: document.getElementById('role_hint') ? document.getElementById('role_hint').value.trim() || null : null,
      linkedin_hint: document.getElementById('linkedin_hint') ? document.getElementById('linkedin_hint').value.trim() || null : null,
      website_hint: document.getElementById('website_hint') ? document.getElementById('website_hint').value.trim() || null : null,
      country_hint: document.getElementById('country_hint') ? document.getElementById('country_hint').value.trim() || null : null,
      industry_hint: document.getElementById('industry_hint') ? document.getElementById('industry_hint').value.trim() || null : null,
      recipient_name: document.getElementById('recipient_name') ? document.getElementById('recipient_name').value.trim() || null : null,
      recipient_role: document.getElementById('recipient_role') ? document.getElementById('recipient_role').value.trim() || null : null,
      mode: 'fast',
      use_cache: useCache,
      demo_case: window.currentDemoCase || null
    };

    // Reset UI
    resetLiveWorkspace(personName || companyName);

    try {
      const res = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`Server returned ${res.status}: ${errText}`);
      }
      const data = await res.json();
      currentRunId = data.run_id;
      if (data.cached) {
        appendLog('s1_resolve', `⚡ Using cached demo results & processes (${data.demo_case || 'scenario'}) — rate-limit safe for recording`);
      }
      startTimer();
      connectSSE(currentRunId);
    } catch (err) {
      alert(`Failed to start run: ${err.message}`);
    }
  });
}

function resetLiveWorkspace(targetName) {
  highestEventId = 0;
  researcherActivity.clear();
  usageRecords.length = 0;
  const processGrid = document.getElementById('researcher-process-grid');
  if (processGrid) processGrid.innerHTML = '<div class="process-placeholder">Research channels will appear when Stage 2 starts.</div>';
  const usageTotal = document.getElementById('usage-total');
  if (usageTotal) usageTotal.textContent = '0 tokens';
  const activeAgentEl = document.getElementById('active-agent-pill');
  if (activeAgentEl) {
    activeAgentEl.textContent = 'Agent: Initializing';
    activeAgentEl.style.color = '#38bdf8';
  }
  ['s0', 's1', 's2', 's3', 's4', 's5', 's6', 's7'].forEach((s) => {
    const badge = document.getElementById(`pagent-${s}`);
    if (badge) {
      badge.className = 'pipeline-agent-badge';
      const statusEl = badge.querySelector('.pagent-status');
      if (statusEl) statusEl.textContent = 'Ready';
    }
  });
  const usageBreakdown = document.getElementById('usage-breakdown');
  if (usageBreakdown) usageBreakdown.textContent = 'Successful model calls and token counts will appear here.';
  const grounding = document.getElementById('grounding-work-content');
  if (grounding) grounding.innerHTML = '<p>Each discovered problem will show its audit status, reviewer note and supporting evidence references here.</p>';
  const groundingSummary = document.getElementById('grounding-summary');
  if (groundingSummary) groundingSummary.textContent = 'Awaiting hypotheses';
  document.getElementById('live-workspace').classList.remove('hidden');
  const s0Card = document.getElementById('s0-clarification-card');
  if (s0Card) s0Card.classList.add('hidden');
  const s1Card = document.getElementById('clarification-card');
  if (s1Card) s1Card.classList.add('hidden');
  const prospectPanel = document.getElementById('resolved-prospect-panel');
  if (prospectPanel) prospectPanel.classList.add('hidden');
  const editDrawer = document.getElementById('edit-prospect-drawer');
  if (editDrawer) editDrawer.classList.add('hidden');
  const profCard = document.getElementById('company-profile-card');
  if (profCard) profCard.classList.add('hidden');
  const roleBar = document.getElementById('role-chip-container');
  if (roleBar) roleBar.style.display = 'none';
  const fbBanner = document.getElementById('fallback-banner');
  if (fbBanner) fbBanner.classList.add('hidden');
  document.getElementById('active-company-tag').textContent = `Target: ${targetName}`;
  document.getElementById('active-status-tag').textContent = 'Status: Initializing';
  document.getElementById('log-stream').innerHTML = '';
  document.getElementById('evidence-list').innerHTML = '';
  document.getElementById('evidence-count').textContent = '0';
  document.getElementById('hypotheses-list').innerHTML = '';
  const solutionBox = document.getElementById('solution-content');
  solutionBox.classList.add('empty-state');
  solutionBox.textContent = 'Designing in S5...';
  const draftBox = document.getElementById('draft-content');
  draftBox.classList.add('empty-state');
  draftBox.textContent = 'Drafting in S6...';
  document.getElementById('review-feedback').classList.add('hidden');
  
  allEvidenceItems = [];
  currentEvidenceFilter = 'all';
  currentHypothesesList = [];
  currentActiveHypId = null;
  currentSelectedLens = 'all';
  const lensFilterEl = document.getElementById('persona-lens-filter');
  if (lensFilterEl) lensFilterEl.value = 'all';
  updateEvidenceFilterCounts();
  setStepperStage(document.getElementById('step-s0') ? 's0' : 's1');
}

// SSE Connection
function connectSSE(runId, fromCurrent = false) {
  if (eventSource) eventSource.close();
  const url = (fromCurrent && highestEventId > 0)
    ? `/api/runs/${runId}/events?last_id=${highestEventId}`
    : `/api/runs/${runId}/events`;
  eventSource = new EventSource(url);

  eventSource.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data);
      if (event.id && event.id > highestEventId) {
        highestEventId = event.id;
      }
      handleStageEvent(event);
    } catch (err) {
      console.error('SSE parse error:', err);
    }
  };

  eventSource.onerror = (err) => {
    console.warn('SSE stream transient error or reconnection...', err);
  };

  startRunWatchdog(runId);
}

function startRunWatchdog(runId) {
  if (window._runWatchdog) clearInterval(window._runWatchdog);
  window._runWatchdog = setInterval(async () => {
    if (currentRunId !== runId) {
      clearInterval(window._runWatchdog);
      return;
    }
    try {
      const res = await fetch(`/api/runs/${runId}`);
      if (!res.ok) return;
      const data = await res.json();
      const run = data.run || {};
      const status = run.status || data.status;

      if (status === 'awaiting_person_clarification') {
        const card = document.getElementById('s0-clarification-card');
        if (card && card.classList.contains('hidden') && run.person_profile) {
          let prof = run.person_profile;
          if (typeof prof === 'string') { try { prof = JSON.parse(prof); } catch(e) {} }
          handlePersonClarificationNeeded({
            confidence: prof.confidence || run.person_confidence,
            person_name: prof.name || run.person_name,
            candidates: prof.alternatives || [],
            questions: prof.clarification_questions || []
          });
        }
      } else if (['completed', 'pending_review', 'approved', 'failed', 'insufficient_evidence'].includes(status)) {
        clearInterval(window._runWatchdog);
      }
    } catch (e) {}
  }, 2500);
}

// Event Dispatcher
function handleStageEvent(ev) {
  appendLog(ev.stage, ev.message);
  setStepperStage(ev.stage);
  document.getElementById('active-status-tag').textContent = `Status: ${ev.stage.replace('_', ' ').toUpperCase()}`;

  switch (ev.event_type) {
    case 'llm_key_rotation':
      handleKeyRotationEvent(ev.payload);
      break;
    case 'researcher_activity':
      renderResearcherActivity(ev.payload || {});
      break;
    case 'llm_usage':
      appendUsageRecord({ ...ev.payload, stage: ev.stage });
      if (ev.payload && ev.payload.provider) {
        handleProviderSuccess(ev.payload.provider, ev.payload.key_index);
      }
      break;
    case 's0_started':
      setStepperStage('s0');
      break;

    case 's0_clarification_needed':
      handlePersonClarificationNeeded(ev.payload);
      break;

    case 's0_resolved':
      if (ev.payload && ev.payload.person_profile) {
        handlePersonResolved(ev.payload.person_profile);
      }
      break;

    case 's0_refinement':
      appendLog('s0_person', ev.message);
      break;

    case 'company_overridden':
      appendLog('s1_resolve', `Target employer overridden to: ${ev.payload.new_company}`);
      setStepperStage('s1');
      break;

    case 'role_overridden':
      appendLog('s3_discovery', `Prospect role overridden to: ${ev.payload.new_role.title_normalized}`);
      setStepperStage('s3');
      break;

    case 'clarification_needed':
      handleClarificationNeeded(ev.payload);
      break;

    case 'identity_confirmed':
      document.getElementById('clarification-card').classList.add('hidden');
      appendLog(ev.stage, `✓ Identity Confirmed: ${ev.payload.identity.name} (${ev.payload.identity.domain})`);
      break;

    case 'recipient_normalised':
      if (ev.payload) {
        updateRoleChipUI(ev.payload);
      }
      break;

    case 'context_validated':
      if (ev.payload) {
        appendLog('sdr_context', `Validated ${ev.payload.count || 0} sender snippets.`);
        if (ev.payload.entity_warnings && ev.payload.entity_warnings.length > 0) {
          ev.payload.entity_warnings.forEach(w => appendLog('sdr_context', `⚠️ Entity Warning: ${w}`));
        }
      }
      break;

    case 'context_evidence_extracted':
      if (ev.payload && ev.payload.items) {
        appendLog('sdr_context', `Extracted ${ev.payload.count || ev.payload.items.length} verified evidence items from sender context.`);
      }
      break;

    case 'role_fit_applied':
      if (ev.payload) {
        appendLog('s4_score', `Role-fit re-weighting applied for lens '${ev.payload.lens}'.`);
      }
      break;

    case 'profile_built':
      if (ev.payload && ev.payload.profile) {
        renderCompanyProfile(ev.payload.profile);
      }
      break;

    case 'evidence_found':
      appendEvidence(ev.payload.evidence);
      break;

    case 'hypothesis_selected':
      if (ev.payload.selected_hypothesis) {
        highlightActiveHypothesis(ev.payload.selected_hypothesis.id);
      }
      break;

    case 'stage_completed':
      if (ev.stage === 's3_discovery' && ev.payload.hypotheses) {
        renderHypotheses(ev.payload.hypotheses);
        renderGroundingWork(ev.payload.hypotheses);
      } else if (ev.stage === 's4_score') {
        const list = ev.payload.ranked_hypotheses || (ev.payload.winner ? [ev.payload.winner] : []);
        const winnerId = ev.payload.winner ? ev.payload.winner.id : null;
        renderHypotheses(list, winnerId);
        if (ev.payload.fallback_info && ev.payload.fallback_info.fallback_banner_used) {
          showFallbackBanner(ev.payload.fallback_info);
        } else {
          hideFallbackBanner();
        }
      } else if (ev.stage === 's5_solution' && ev.payload.solution) {
        renderSolution(ev.payload.solution);
      } else if (ev.stage === 's6_draft' && ev.payload.draft) {
        renderDraft(ev.payload.draft);
      } else if (ev.stage === 's7_check' && ev.payload.report) {
        renderQualityReport(ev.payload.report, ev.payload.draft);
      }
      break;

    case 'run_completed':
      stopTimer();
      document.querySelectorAll('.btn-select-hyp').forEach(btn => { btn.disabled = false; btn.style.opacity = '1'; });
      if (ev.payload && ev.payload.reason === 'insufficient_evidence') {
        setStepperStage('s3', true);
        document.getElementById('active-status-tag').textContent = 'Status: More Evidence Needed';
      } else {
        setStepperStage('s7', true);
        document.getElementById('active-status-tag').textContent = 'Status: Ready for Human Review';
        appendLog('complete', `🎉 Pipeline completed in ${ev.payload.total_duration || ''}s`);
      }
      if (eventSource) eventSource.close();
      break;

    case 'stage_failed':
      stopTimer();
      document.querySelectorAll('.btn-select-hyp').forEach(btn => { btn.disabled = false; btn.style.opacity = '1'; });
      document.getElementById('active-status-tag').textContent = 'Status: FAILED';
      appendLog('error', `❌ Error: ${ev.message}`);
      if (eventSource) eventSource.close();
      break;
  }
}

const researcherActivity = new Map();
const usageRecords = [];
function renderResearcherActivity(item) {
  if (!item.researcher) return;
  researcherActivity.set(item.researcher, item);
  const grid = document.getElementById('researcher-process-grid');
  if (!grid) return;
  grid.innerHTML = [...researcherActivity.values()].map((row) => {
    const state = row.state || 'queued';
    const evidence = row.evidence_count ? `${row.evidence_count} candidates` : state === 'completed' ? 'No candidates returned' : 'Working';
    return `<article class="process-agent ${escapeHtml(state)}"><span class="process-state">${escapeHtml(state)}</span><strong>${escapeHtml(row.researcher.replaceAll('_', ' '))}</strong><small>${escapeHtml(evidence)}${row.duration ? ` · ${Number(row.duration).toFixed(1)}s` : ''}</small></article>`;
  }).join('');
}

function renderGroundingWork(hypotheses) {
  const content = document.getElementById('grounding-work-content');
  const summary = document.getElementById('grounding-summary');
  if (!content) return;
  const list = Array.isArray(hypotheses) ? hypotheses : [];
  const verified = list.filter(h => h.grounding_status === 'verified').length;
  if (summary) summary.textContent = `${verified} verified · ${list.length - verified} needs review`;
  if (!list.length) {
    content.innerHTML = '<p>No hypotheses were returned for the grounding review.</p>';
    return;
  }
  content.innerHTML = list.map(h => {
    const ids = Array.isArray(h.evidence_ids) ? h.evidence_ids : [];
    const status = h.grounding_status || 'review needed';
    const refs = ids.map(id => `<button type="button" class="grounding-ref" onclick="highlightEvidenceItem('${escapeHtml(id)}')">${escapeHtml(id)}</button>`).join('');
    return `<article class="grounding-row"><div><strong>${escapeHtml(h.problem || 'Unnamed hypothesis')}</strong><span class="grounding-status ${status === 'verified' ? 'ok' : 'review'}">${escapeHtml(status)}</span></div><p>${escapeHtml(h.grounding_critique || 'No separate audit note was returned.')}</p><small>Supporting evidence: ${refs || 'None linked'}</small></article>`;
  }).join('');
}

function appendUsageRecord(record) {
  usageRecords.push(record);
  const total = usageRecords.reduce((sum, row) => sum + (Number(row.input_tokens) || 0) + (Number(row.output_tokens) || 0), 0);
  const totalEl = document.getElementById('usage-total');
  if (totalEl) totalEl.textContent = `${total.toLocaleString()} tokens`;
  const breakdown = document.getElementById('usage-breakdown');
  if (!breakdown) return;
  breakdown.innerHTML = usageRecords.slice(-8).reverse().map(row => `<span>${escapeHtml(row.stage || '')} · ${escapeHtml(row.provider || '')}/${escapeHtml(row.model || '')}: ${(Number(row.input_tokens)||0).toLocaleString()} in / ${(Number(row.output_tokens)||0).toLocaleString()} out</span>`).join('');
}

function updateRoleChipUI(info) {
  const bar = document.getElementById('role-chip-container');
  if (!bar) return;
  if (!info || (!info.title && !info.recipient_title)) {
    bar.style.display = 'none';
    return;
  }
  const nameEl = document.getElementById('role-display-name');
  const titleEl = document.getElementById('role-display-title');
  const lensEl = document.getElementById('role-display-lens');
  const senEl = document.getElementById('role-display-seniority');
  const unrecogEl = document.getElementById('role-unrecognized-chip');

  const title = info.title || info.recipient_title || 'Recipient';
  const nameInput = document.getElementById('recipient_name') ? document.getElementById('recipient_name').value.trim() : '';
  if (nameEl) nameEl.textContent = nameInput ? nameInput : (info.recipient_name || 'Recipient');
  if (titleEl) titleEl.textContent = title;
  if (lensEl) lensEl.textContent = info.lens || 'broad';
  if (senEl) senEl.textContent = (info.seniority || 'director_or_head').replace(/_/g, ' ');

  if (unrecogEl) {
    if (info.role_unrecognized) {
      unrecogEl.classList.remove('hidden');
    } else {
      unrecogEl.classList.add('hidden');
    }
  }
  bar.style.display = 'flex';
}

function showFallbackBanner(fbInfo) {
  const banner = document.getElementById('fallback-banner');
  if (!banner) return;
  const msgEl = document.getElementById('fallback-banner-text');
  if (msgEl) msgEl.textContent = fbInfo.banner_message || "No strong problem was found in this role's area. Drafting for best company-level problem instead.";
  
  const chipsBox = document.getElementById('better-fit-chips');
  if (chipsBox) {
    chipsBox.innerHTML = '';
    const roles = fbInfo.suggested_roles || [];
    roles.forEach(r => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'better-fit-chip';
      chip.textContent = r;
      chip.title = `Click to re-target as ${r}`;
      chip.onclick = () => {
        if (document.getElementById('recipient_role')) {
          document.getElementById('recipient_role').value = r;
          alert(`Suggested role '${r}' selected. Re-run the pipeline to generate outreach targeted to this buyer.`);
        }
      };
      chipsBox.appendChild(chip);
    });
  }
  banner.classList.remove('hidden');
}

function hideFallbackBanner() {
  const banner = document.getElementById('fallback-banner');
  if (banner) banner.classList.add('hidden');
}

function appendLog(stage, message) {
  const stream = document.getElementById('log-stream');
  const d = new Date();
  const timeStr = d.toTimeString().split(' ')[0];
  const row = document.createElement('div');
  row.className = 'log-entry';
  row.innerHTML = `
    <span class="log-time">[${timeStr}]</span>
    <span class="log-stage">[${stage}]</span>
    <span class="log-msg">${escapeHtml(message)}</span>
  `;
  stream.appendChild(row);
  stream.scrollTop = stream.scrollHeight;
}

function renderCompanyProfile(profile, companyName) {
  if (!profile) return;
  const card = document.getElementById('company-profile-card');
  if (!card) return;

  const nameEl = document.getElementById('prof-company-name');
  const sumEl = document.getElementById('prof-summary');
  const doesEl = document.getElementById('prof-what-it-does');
  const consEl = document.getElementById('prof-consumers');
  const modEl = document.getElementById('prof-model');
  const trajEl = document.getElementById('prof-trajectory');
  const sourcesBar = document.getElementById('prof-sources-bar');
  const sourcesList = document.getElementById('prof-sources-list');

  if (nameEl) nameEl.textContent = companyName ? `${companyName} Profile` : 'Company Profile';
  if (sumEl) sumEl.textContent = profile.summary || '';
  if (doesEl) doesEl.textContent = profile.what_it_does || 'N/A';
  if (consEl) consEl.textContent = profile.target_consumers || 'N/A';
  if (modEl) modEl.textContent = profile.business_model || 'N/A';
  if (trajEl) trajEl.textContent = profile.trajectory || 'N/A';

  if (sourcesBar && sourcesList) {
    if (profile.sources && profile.sources.length > 0) {
      sourcesList.innerHTML = profile.sources.map(src => {
        let domain = src;
        try { domain = new URL(src).hostname; } catch(e) {}
        return `<a href="${escapeHtml(src)}" target="_blank" rel="noreferrer" class="prof-source-chip">🔗 ${escapeHtml(domain)}</a>`;
      }).join('');
      sourcesBar.classList.remove('hidden');
    } else {
      sourcesBar.classList.add('hidden');
    }
  }

  card.classList.remove('hidden');
}

// Evidence Filter & Feed State
let allEvidenceItems = [];
let currentEvidenceFilter = 'all';

function appendEvidence(ev) {
  if (!ev) return;
  // Deduplicate by ID
  if (!allEvidenceItems.some(item => item.id === ev.id)) {
    allEvidenceItems.unshift(ev);
  }
  updateEvidenceFilterCounts();
  renderFilteredEvidence();
}

function updateEvidenceFilterCounts() {
  const total = allEvidenceItems.length;
  document.getElementById('evidence-count').textContent = total;
  const countEl = document.getElementById('ev-filter-all-count');
  if (countEl) countEl.textContent = total;
}

function filterEvidence(category) {
  currentEvidenceFilter = category;
  document.querySelectorAll('.filter-chip').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-filter') === category);
  });
  renderFilteredEvidence();
}

function renderFilteredEvidence() {
  const container = document.getElementById('evidence-list');
  container.innerHTML = '';

  // Update Quantitative Authority & Summary Metrics Bar
  if (allEvidenceItems.length > 0) {
    const sumAuth = allEvidenceItems.reduce((acc, e) => acc + (typeof e.authority_score === 'number' ? e.authority_score : 0.85), 0);
    const avgAuthPct = Math.round((sumAuth / allEvidenceItems.length) * 100);
    const avgEl = document.getElementById('avg-auth-val');
    if (avgEl) avgEl.textContent = `${avgAuthPct}%`;
    
    const recText = document.getElementById('recency-summary-text');
    if (recText) recText.textContent = `${allEvidenceItems.length} Signals (${avgAuthPct}% Mean Auth)`;
  }

  const filtered = allEvidenceItems.filter(ev => {
    if (currentEvidenceFilter === 'all') return true;
    const st = (ev.source_type || '').toLowerCase();
    const res = (ev.researcher || '').toLowerCase();
    if (currentEvidenceFilter === 'community') return st === 'community' || res.includes('reddit') || res.includes('community');
    if (currentEvidenceFilter === 'review') return st === 'review' || res.includes('review') || res.includes('app_review') || res.includes('fulfillment');
    if (currentEvidenceFilter === 'status_incident') return st === 'status_incident' || res.includes('status') || res.includes('incident') || res.includes('outage');
    if (currentEvidenceFilter === 'changelog') return st === 'changelog' || res.includes('changelog') || res.includes('migration') || res.includes('release');
    if (currentEvidenceFilter === 'person_voice') return st === 'person_voice' || res.includes('person_voice') || res.includes('voice');
    if (currentEvidenceFilter === 'exec_voice') return st === 'exec_voice' || res.includes('exec') || res.includes('priorities') || res.includes('voice');
    if (currentEvidenceFilter === 'compliance') return st === 'compliance' || res.includes('compliance') || res.includes('regulatory') || res.includes('filing');
    if (currentEvidenceFilter === 'website') return st === 'website' || res.includes('site') || res.includes('overview');
    if (currentEvidenceFilter === 'careers') return st === 'careers' || res.includes('hiring') || res.includes('operations');
    if (currentEvidenceFilter === 'news') return st === 'news' || res.includes('news') || res.includes('scale');
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state">No evidence items matching '${currentEvidenceFilter}'.</div>`;
    return;
  }

  filtered.forEach(ev => {
    const item = document.createElement('div');
    item.className = 'evidence-item';
    item.id = `ev-item-${ev.id}`;
    const isSdr = (ev.source_type === 'sdr_provided' || ev.researcher === 'sender_context');
    const isPersonVoice = (ev.source_type === 'person_voice');
    const tierClass = `tier-${(ev.reliability_tier || 'b').toLowerCase()}`;
    const authScore = Math.round((typeof ev.authority_score === 'number' ? ev.authority_score : 0.85) * 100);
    const authClass = authScore >= 88 ? 'auth-pill-high' : (authScore >= 75 ? 'auth-pill-mid' : 'auth-pill-low');

    const metaRightHtml = isSdr ? `
      <span class="badge" style="background: rgba(168, 85, 247, 0.18); color: #C084FC; border: 1px solid rgba(168, 85, 247, 0.4); font-size: 0.72rem; padding: 2px 7px; border-radius: 4px;">📎 Provided by sender</span>
      <span style="font-size: 0.68rem; color: #94A3B8; font-style: italic;">Unverified by design</span>
    ` : `
      ${isPersonVoice ? `<span class="badge" style="background: rgba(16, 185, 129, 0.18); color: #34D399; border: 1px solid rgba(16, 185, 129, 0.4); font-size: 0.72rem; padding: 2px 7px; border-radius: 4px;">🎙️ Person Voice</span>` : ''}
      ${ev.published_date ? `<span class="badge-date" style="font-size: 0.68rem; color: #94A3B8; background: rgba(255,255,255,0.05); padding: 2px 6px; border-radius: 4px;">📅 ${escapeHtml(ev.published_date)}</span>` : ''}
      <span class="auth-pill ${authClass}" title="Quantitative Source Authority Score: ${authScore}%">🏛️ Auth: ${authScore}%</span>
      <span class="tier-badge ${tierClass}">Tier ${ev.reliability_tier || 'B'}</span>
    `;

    item.innerHTML = `
      <div class="evidence-meta">
        <span class="badge-source">${escapeHtml(ev.researcher)}</span>
        <div style="display: flex; align-items: center; gap: 6px;">
          ${metaRightHtml}
        </div>
      </div>
      <div class="evidence-claim">${escapeHtml(ev.claim)}</div>
      <div class="evidence-excerpt">"${escapeHtml(ev.excerpt)}"</div>
      <div style="margin-top: 6px; display: flex; justify-content: space-between; align-items: center;">
        <a href="${escapeHtml(ev.url)}" target="_blank" rel="noreferrer" style="color: #60A5FA; font-size: 0.72rem; text-decoration: none;">🔗 Source Reference</a>
        <span style="font-family: monospace; font-size: 0.68rem; color: #64748B;">ID: ${escapeHtml(ev.id)}</span>
      </div>
    `;
    container.appendChild(item);
  });
}

function highlightEvidenceItem(evId) {
  if (currentEvidenceFilter !== 'all') {
    filterEvidence('all');
  }
  const el = document.getElementById(`ev-item-${evId}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('highlighted');
    setTimeout(() => el.classList.remove('highlighted'), 2500);
  }
}

// Hypotheses Ranking & Interactive Selection State
let currentHypothesesList = [];
let currentActiveHypId = null;

function renderHypotheses(hypotheses, activeHypId = null) {
  if (!hypotheses || hypotheses.length === 0) return;

  // Sort descending by final score
  currentHypothesesList = hypotheses.slice().sort((a, b) => (b.final_score || 0) - (a.final_score || 0));

  if (!activeHypId && currentHypothesesList.length > 0) {
    activeHypId = currentHypothesesList[0].id;
  }
  if (activeHypId) {
    currentActiveHypId = activeHypId;
  }

  const container = document.getElementById('hypotheses-list');
  container.innerHTML = '';

  currentHypothesesList.forEach((h, idx) => {
    const rank = h.rank || (idx + 1);
    const rawScore = h.final_score || 0;
    // Format score nicely (e.g. 84 / 100 or 0.84)
    const scoreVal = rawScore > 1 ? rawScore.toFixed(1) : (rawScore * 100).toFixed(1);
    const isActive = (h.id === currentActiveHypId);

    // Score components
    const scores = typeof h.scores === 'object' && h.scores !== null ? h.scores : {
      strength: h.evidence_strength || 0.7,
      impact: h.business_impact || 0.7,
      auto: h.automatability || 0.75,
      timeliness: h.timeliness || 0.6,
      credibility: h.buyer_credibility || 0.7
    };

    const item = document.createElement('div');
    item.className = `hypothesis-item ${isActive ? 'winner active-selection' : ''}`;
    item.id = `hypo-${h.id}`;
    item.setAttribute('data-lens', h.lens || 'operations');

    // Supporting evidence chips
    const evIds = Array.isArray(h.evidence_ids) ? h.evidence_ids : [];
    const evTagsHtml = evIds.map(eid => `
      <span class="hyp-ev-chip" onclick="highlightEvidenceItem('${eid}')" title="Click to view hook evidence in left feed">
        🔗 ${escapeHtml(eid)}
      </span>
    `).join('');

    const timelinessVal = (typeof scores.timeliness === 'number') ? scores.timeliness : ((typeof h.timeliness === 'number') ? h.timeliness : 0.7);

    // Score breakdown components
    const b = (typeof h.score_breakdown === 'object' && h.score_breakdown !== null) ? h.score_breakdown : {
      evidence_strength: scores.strength || 0.7,
      business_impact: scores.impact || 0.7,
      automatability: scores.auto || 0.75,
      timeliness: scores.timeliness || 0.6,
      buyer_credibility: scores.credibility || 0.7,
      avg_source_authority: 0.85,
      raw_composite: rawScore,
      layer_mult: h.layer === 'stated' ? 1.0 : (h.layer === 'implied' ? 0.9 : 0.6),
      freshness_mult: (timelinessVal < 0.5) ? 0.65 : 1.0,
      final_score: rawScore
    };

    // Category Label & Grounding Guard
    const groundingNeedsReview = h.grounding_status !== 'verified';
    const isDirect = (h.category_label || '').toLowerCase().includes('direct') || (h.layer || '').toLowerCase() === 'stated';
    const categoryBadge = isDirect
      ? `<span class="hyp-category-badge category-direct" title="Explicitly mentioned in user reviews, Reddit, or company announcements">🎯 DIRECT / STATED</span>`
      : `<span class="hyp-category-badge category-inferred" title="Inferred operational risk deduced from trajectory and scaling facts">💡 INFERRED / ASSUMED</span>`;

    // Role-fit badge
    const roleBadge = h.role_fit_badge || (b && b.role_fit_badge) || 'broad';
    let roleBadgeHtml = '';
    if (roleBadge === 'primary') {
      roleBadgeHtml = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #34D399; font-weight: 700; font-size: 0.72rem; padding: 2px 7px; border-radius: 4px; border: 1px solid rgba(16, 185, 129, 0.4);" title="Primary lens for recipient's role (1.0x multiplier)">🎯 Primary (1.0x)</span>`;
    } else if (roleBadge === 'adjacent') {
      roleBadgeHtml = `<span class="badge" style="background: rgba(59, 130, 246, 0.2); color: #60A5FA; font-weight: 700; font-size: 0.72rem; padding: 2px 7px; border-radius: 4px; border: 1px solid rgba(59, 130, 246, 0.4);" title="Adjacent lens for recipient's role (0.85x multiplier)">🔄 Adjacent (0.85x)</span>`;
    } else if (roleBadge === 'other') {
      roleBadgeHtml = `<span class="badge" style="background: rgba(156, 163, 175, 0.2); color: #9CA3AF; font-size: 0.72rem; padding: 2px 7px; border-radius: 4px; border: 1px solid rgba(156, 163, 175, 0.3);" title="Unrelated lens for recipient's role (0.60x multiplier)">Other Lens (0.60x)</span>`;
    }

    // Recency & Staleness Badge (Prominent Top-Level Header Badge)
    const recencyBadge = timelinessVal >= 0.75
      ? `<span class="hyp-recency-badge recency-active" title="Active and ongoing operational friction in current period">🟢 ACTIVE &amp; ONGOING</span>`
      : (timelinessVal < 0.50
        ? `<span class="hyp-recency-badge recency-stale" title="Past seasonal event or older than 90 days">⚠️ PAST / SEASONAL</span>`
        : `<span class="hyp-recency-badge recency-moderate" title="Recurring pattern across recent quarters">🟡 RECURRING</span>`);

    const groundingCritiqueHtml = h.grounding_critique ? `
      <div class="hyp-grounding-critique">
        <span class="grounding-guard-pill">🛡️ Grounding Guard:</span>
        <span class="grounding-guard-text">${escapeHtml(h.grounding_critique)}</span>
      </div>
    ` : '';

    item.innerHTML = `
      <div class="hyp-header">
        <div class="hyp-badges-left">
          <span class="hyp-rank-badge ${rank === 1 ? 'rank-1' : ''}">#${rank} ${rank === 1 ? 'TOP RANK' : 'RANK'}</span>
          ${categoryBadge}
          ${roleBadgeHtml}
          ${recencyBadge}
          <span class="layer-badge layer-${h.layer}">${h.layer}</span>
          <span class="hyp-lens-pill">Operational Lens: ${escapeHtml(h.lens)}</span>
        </div>
        <div class="hyp-score-box">
          <span class="hyp-score">${scoreVal}</span>
          <span class="hyp-score-sub">/ 100</span>
        </div>
      </div>

      <div class="hyp-problem-title">${escapeHtml(h.problem)}</div>
      ${groundingCritiqueHtml}

      ${h.lens_explanation ? `
        <div class="hyp-lens-explanation">
          ℹ️ ${escapeHtml(h.lens_explanation)}
        </div>
      ` : ''}

      <div class="score-breakdown-row">
        <span class="score-mini-pill">Evidence: <span>${(scores.strength || 0).toFixed(2)}</span></span>
        <span class="score-mini-pill">Impact: <span>${(scores.impact || 0).toFixed(2)}</span></span>
        <span class="score-mini-pill">Auto: <span>${(scores.auto || 0).toFixed(2)}</span></span>
        <span class="score-mini-pill ${scores.timeliness < 0.5 ? 'pill-stale' : (scores.timeliness >= 0.75 ? 'pill-fresh' : '')}">
          Recency: <span>${(scores.timeliness || 0).toFixed(2)}</span> ${scores.timeliness >= 0.75 ? '🟢 Active' : (scores.timeliness < 0.5 ? '⚠️ Past Campaign' : '🟡')}
        </span>
        <span class="score-mini-pill">Credibility: <span>${(scores.credibility || 0).toFixed(2)}</span></span>
        <button type="button" class="btn-breakdown-toggle" onclick="toggleScoreBreakdown('${h.id}', event)" title="View exact S4 mathematical formula components">
          🧮 Score Breakdown
        </button>
      </div>

      <div id="breakdown-${h.id}" class="score-breakdown-drawer hidden">
        <div class="breakdown-title">Deterministic Scoring Formula (S4)</div>
        <div class="formula-math">
          Role Adjusted Score = Base Score (${Number(b.base_score || h.base_score || rawScore).toFixed(3)}) × Role Fit (${Number(b.role_fit || h.role_fit || 1.0).toFixed(2)}) = <strong>${scoreVal}</strong>
          <br>
          <span class="formula-math-sub">Base Score = Layer (${(b.layer_mult || 1.0).toFixed(2)}) × Freshness (${(b.freshness_mult || 1.0).toFixed(2)}) × Composite [${Number(b.raw_composite || 0).toFixed(3)}]</span>
        </div>
        <div class="breakdown-grid">
          <div><span>Base Company Score:</span> <strong>${Number(b.base_score || h.base_score || rawScore).toFixed(3)}</strong></div>
          <div><span>Role Fit Factor:</span> <strong>${Number(b.role_fit || h.role_fit || 1.0).toFixed(2)}x (${roleBadge})</strong></div>
          <div><span>Role Adjusted Score:</span> <strong>${scoreVal}</strong></div>
          <div><span>Evidence Strength (30%):</span> <strong>${Number(b.evidence_strength || 0).toFixed(2)}</strong></div>
          <div><span>Business Impact (25%):</span> <strong>${Number(b.business_impact || 0).toFixed(2)}</strong></div>
          <div><span>Automatability (20%):</span> <strong>${Number(b.automatability || 0).toFixed(2)}</strong></div>
          <div><span>Timeliness (15%):</span> <strong>${Number(b.timeliness || 0).toFixed(2)}</strong></div>
          <div><span>Buyer Credibility (10%):</span> <strong>${Number(b.buyer_credibility || 0).toFixed(2)}</strong> (Auth: ${Math.round((b.avg_source_authority || 0.85) * 100)}%)</div>
          <div><span>Raw Composite:</span> <strong>${Number(b.raw_composite || 0).toFixed(3)}</strong></div>
        </div>
      </div>

      <div class="hyp-structured-diag">
        ${h.root_cause ? `
          <div class="hyp-diag-row">
            <span class="hyp-diag-label">🔴 Root Cause:</span>
            <span class="hyp-diag-val">${escapeHtml(h.root_cause)}</span>
          </div>
        ` : ''}
        ${h.workflow_burden ? `
          <div class="hyp-diag-row">
            <span class="hyp-diag-label">⚙️ Workflow Burden:</span>
            <span class="hyp-diag-val">${escapeHtml(h.workflow_burden)}</span>
          </div>
        ` : ''}
        ${h.automation_fit ? `
          <div class="hyp-diag-row">
            <span class="hyp-diag-label">🚀 Automation Fit:</span>
            <span class="hyp-diag-val">${escapeHtml(h.automation_fit)}</span>
          </div>
        ` : ''}
        ${(!h.root_cause && h.rationale) ? `
          <div class="hyp-diag-row">
            <span class="hyp-diag-label">💡 Rationale:</span>
            <span class="hyp-diag-val">${escapeHtml(h.rationale)}</span>
          </div>
        ` : ''}
      </div>

      ${evTagsHtml ? `
        <div class="hyp-evidence-tags">
          <span class="hyp-evidence-label">Supporting Hooks:</span>
          ${evTagsHtml}
        </div>
      ` : ''}

      <div class="hyp-action-bar">
        ${isActive ? `
          ${groundingNeedsReview
            ? '<span class="badge-grounding-pending">SELECTED - GROUNDING REVIEW NEEDED</span>'
            : '<span class="badge-active-hyp">ACTIVE FOR OUTREACH</span>'}
          <span class="hyp-action-note">${groundingNeedsReview ? 'Draft prepared; verify the cited evidence before outreach.' : 'Architecture &amp; Draft Built for This Problem'}</span>
        ` : `
          <span class="hyp-action-note">Alternative Hypothesis</span>
          <button type="button" class="btn-select-hyp" onclick="selectProblemHypothesis('${h.id}')">
            Select Problem &amp; Generate Outreach
          </button>
        `}
      </div>
    `;

    container.appendChild(item);
  });
}

function highlightWinningHypothesis(winnerId) {
  highlightActiveHypothesis(winnerId);
}

function highlightActiveHypothesis(winnerId) {
  currentActiveHypId = winnerId;
  renderHypotheses(currentHypothesesList, winnerId);
}

function toggleScoreBreakdown(hypId, event) {
  if (event) event.stopPropagation();
  const drawer = document.getElementById(`breakdown-${hypId}`);
  if (drawer) {
    drawer.classList.toggle('hidden');
  }
}

let currentSelectedLens = 'all';

function filterHypothesesByLens(lens) {
  currentSelectedLens = lens;
  const items = document.querySelectorAll('.hypothesis-item');
  items.forEach(el => {
    if (lens === 'all') {
      el.style.display = '';
    } else {
      const elLens = (el.getAttribute('data-lens') || '').toLowerCase();
      if (elLens.includes(lens) || (lens === 'operations' && elLens.includes('ops'))) {
        el.style.display = '';
      } else {
        el.style.display = 'none';
      }
    }
  });
}

async function selectProblemHypothesis(hypId) {
  if (!currentRunId) {
    alert('No active run selected.');
    return;
  }
  appendLog('s4_score', `Switching active hypothesis to: ${hypId}...`);
  highlightActiveHypothesis(hypId);

  // Set visual stepper indicator to S5
  setStepperStage('s5');
  const statusTag = document.getElementById('active-status-tag');
  if (statusTag) statusTag.textContent = 'Status: S5 SOLUTION DESIGN';

  // Disable hypothesis selection buttons during generation
  const selectBtns = document.querySelectorAll('.btn-select-hyp');
  selectBtns.forEach(btn => {
    btn.disabled = true;
    btn.style.opacity = '0.6';
  });

  // Clear right column indicators while regenerating
  const solutionBox = document.getElementById('solution-content');
  solutionBox.classList.add('empty-state');
  solutionBox.textContent = 'Regenerating Solution Architecture in S5...';
  const draftBox = document.getElementById('draft-content');
  draftBox.classList.add('empty-state');
  draftBox.textContent = 'Regenerating Grounded Outreach in S6...';

  // Ensure EventSource is connected from the latest event so live S5, S6, S7 events are received
  connectSSE(currentRunId, true);

  // Polling fallback to guarantee UI updates even if SSE stream drops
  let pollCount = 0;
  const pollInterval = setInterval(async () => {
    pollCount++;
    if (pollCount > 60) {
      clearInterval(pollInterval);
      selectBtns.forEach(btn => { btn.disabled = false; btn.style.opacity = '1'; });
      return;
    }
    try {
      const res = await fetch(`/api/runs/${currentRunId}`);
      if (res.ok) {
        const data = await res.json();
        const runStatus = (data.run && data.run.status) || data.status;
        const selectedHyp = (data.run && data.run.selected_hypothesis_id) || data.selected_hypothesis_id;

        // Render solution as soon as it matches the selected hypothesis
        if (data.solution && data.solution.hypothesis_id === hypId) {
          renderSolution(data.solution);
        }

        // Only render draft once the draft for this hypothesis is ready
        const isDraftForHyp = data.draft && (
          data.draft.hypothesis_id === hypId ||
          (runStatus === 'pending_review' && selectedHyp === hypId && data.solution && data.solution.hypothesis_id === hypId)
        );

        if (isDraftForHyp) {
          renderDraft(data.draft);
          if (data.draft.quality_report) {
            renderQualityReport(data.draft.quality_report, data.draft);
          }
          clearInterval(pollInterval);
          selectBtns.forEach(btn => { btn.disabled = false; btn.style.opacity = '1'; });
        }
      }
    } catch (e) {
      // transient poll error, continue
    }
  }, 1500);

  try {
    const res = await fetch(`/api/runs/${currentRunId}/select_problem`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hypothesis_id: hypId })
    });
    if (!res.ok) {
      const err = await res.json();
      clearInterval(pollInterval);
      selectBtns.forEach(btn => { btn.disabled = false; btn.style.opacity = '1'; });
      alert('Error selecting hypothesis: ' + (err.detail || 'Request failed'));
    }
  } catch (err) {
    clearInterval(pollInterval);
    selectBtns.forEach(btn => { btn.disabled = false; btn.style.opacity = '1'; });
    console.error('Error selecting hypothesis:', err);
    alert('Failed to select hypothesis: ' + err.message);
  }
}

function renderSolution(sol) {
  const box = document.getElementById('solution-content');
  box.classList.remove('empty-state');
  box.innerHTML = `
    <div class="solution-box">
      <div class="solution-field">
        <strong>Process Architecture</strong>
        <div class="solution-process-name">${escapeHtml(sol.process_name)}</div>
      </div>
      <div class="solution-field">
        <strong>What it Automates</strong>
        <div>${escapeHtml(sol.what_it_automates)}</div>
      </div>
      <div class="solution-field">
        <strong>Input Ingested</strong>
        <div>${escapeHtml(sol.input_consumed)}</div>
      </div>
      <div class="solution-field">
        <strong>Key Steps</strong>
        <ul style="padding-left: 18px; margin-top: 4px;">
          ${sol.key_steps.map(s => `<li>${escapeHtml(s)}</li>`).join('')}
        </ul>
      </div>
      <div class="solution-field">
        <strong>Human-in-the-Loop Safeguards</strong>
        <div>${sol.human_checkpoints ? sol.human_checkpoints.join(', ') : 'Standard threshold escalation'}</div>
      </div>
      <div class="solution-field">
        <strong>Impact Direction</strong>
        <div class="solution-impact">${escapeHtml(sol.impact_direction)}</div>
      </div>
    </div>
  `;
}

function renderDraft(draft) {
  currentDraftId = draft.id;
  const box = document.getElementById('draft-content');
  box.classList.remove('empty-state');
  const alts = Array.isArray(draft.subject_alternatives) ? draft.subject_alternatives : [];
  const altsHtml = alts.length > 0 ? `
    <div class="subject-alternatives-bar">
      <span style="font-size: 0.72rem; color: #94A3B8; margin-right: 6px; font-weight: 600;">Alternative Angles:</span>
      ${alts.map(s => `
        <button type="button" class="subject-alt-chip" onclick="swapSubjectLine('${escapeHtml(s).replace(/'/g, "\\'")}')" title="Click to apply this subject line">
          ${escapeHtml(s)}
        </button>
      `).join('')}
    </div>
  ` : '';

  const draftStyle = draft.draft_style || 'direct';
  const isInferred = draftStyle === 'inferred';
  const needsReview = draftStyle === 'review';
  const styleBadge = isInferred
    ? `<span class="draft-style-badge inferred" title="An inferred opportunity is presented as a hypothesis, not a confirmed pain.">◈ INFERRED</span>`
    : needsReview
      ? `<span class="draft-style-badge review" title="Grounding was not confirmed. Validate the evidence and problem before using this draft.">REVIEW NEEDED</span>`
      : `<span class="draft-style-badge direct" title="Grounded in a directly observed operational issue.">✓ DIRECT</span>`;

  const personHookBadge = draft.person_hook_cited
    ? `<span class="person-hook-badge" title="Opening grounded in sender-provided recipient text with verified exact match">PERSON HOOK CITED</span>`
    : '';

  box.innerHTML = `
    <div class="draft-body-box">
      <div class="draft-subject-container">
        <span class="draft-subject-label">Subject:</span>
        <span class="draft-subject" id="draft-subject-editable" contenteditable="true" title="Click to edit subject line directly">${escapeHtml(draft.subject)}</span>
        ${styleBadge}
        ${personHookBadge}
      </div>
      ${altsHtml}
      <div class="draft-body-text" id="draft-body-editable" contenteditable="true">${escapeHtml(draft.body)}</div>
    </div>
    <div class="linkedin-note-box">
      <strong>LinkedIn InMail / Connection Note:</strong>
      <span>${escapeHtml(draft.linkedin_note)}</span>
    </div>
    <div class="why-hook-box">
      <strong>SDR Internal Guidance (Why this hook?):</strong>
      <span>${escapeHtml(draft.why_this_hook)}</span>
    </div>
  `;
}

function swapSubjectLine(newSubj) {
  const el = document.getElementById('draft-subject-editable');
  if (el) {
    el.textContent = newSubj;
    el.classList.add('flash-highlight');
    setTimeout(() => el.classList.remove('flash-highlight'), 800);
  }
}

function renderQualityReport(report, draft) {
  const box = document.getElementById('quality-report-box');
  if (box) box.classList.remove('hidden');

  const badge = document.getElementById('quality-badge') || document.getElementById('quality-verdict-badge');
  if (badge) {
    badge.textContent = `QA: ${report.verdict.toUpperCase()}`;
    badge.className = `quality-badge quality-${report.verdict === 'pass' ? 'pass' : (report.verdict === 'pass_with_repair' ? 'repair' : 'flagged')}`;
  }
  
  const stats = document.getElementById('quality-stats');
  if (stats) {
    stats.textContent = `${report.word_count || (draft && draft.body ? draft.body.split(/\s+/).length : 0)} words · ${report.unsupported_claims && report.unsupported_claims.length === 0 ? 'Zero ungrounded claims' : `${report.unsupported_claims.length} claims flagged`}`;
  }

  const swapStatus = document.getElementById('swap-test-status');
  if (swapStatus) {
    swapStatus.innerHTML = `
      <span class="badge ${report.passed_swap_test ? 'badge-pass' : 'badge-fail'}">
        ${report.passed_swap_test ? '✓ Swap-The-Name Test Passed' : '⚠️ Swap-The-Name Risk Detected'}
      </span>
    `;
  }

  const swapRoleStatus = document.getElementById('swap-role-status');
  if (swapRoleStatus) {
    const passedRole = !report.notes || !report.notes.some(n => n.toLowerCase().includes('swap-the-role failed'));
    swapRoleStatus.innerHTML = `
      <span class="badge ${passedRole ? 'badge-pass' : 'badge-fail'}">
        ${passedRole ? '✓ Swap-The-Role Test Passed (Functionally Targeted)' : '⚠️ Swap-The-Role Alert'}
      </span>
    `;
  }

  renderGroundingQa(report);

  const notesEl = document.getElementById('quality-notes');
  if (notesEl && report.notes && report.notes.length > 0) {
    notesEl.innerHTML = report.notes.map(n => `<div class="quality-note-item" style="font-size: 0.78rem; color: #94A3B8; margin-top: 3px;">• ${escapeHtml(n)}</div>`).join('');
  }

  if (draft && draft.body) {
    const bodyEl = document.getElementById('draft-body-editable');
    if (bodyEl) bodyEl.textContent = draft.body;
  }
}


function renderGroundingQa(report) {
  const content = document.getElementById('grounding-work-content');
  if (!content || !report) return;
  content.querySelector('.grounding-qa')?.remove();
  const flagged = Array.isArray(report.unsupported_claims) ? report.unsupported_claims : [];
  const notes = Array.isArray(report.notes) ? report.notes : [];
  const checks = [
    ['Draft verdict', report.verdict || 'not reported'],
    ['Name swap check', report.passed_swap_test ? 'passed' : (notes.some(note => String(note).toLowerCase().includes('swap test unavailable')) ? 'unavailable' : 'not passed')],
    ['Unsupported claims', flagged.length ? `${flagged.length} flagged` : 'none flagged'],
    ['Invented numbers', report.invented_numbers_detected ? 'flagged' : 'none flagged'],
    ['Draft length', `${Number(report.word_count) || 0} words`]
  ];
  const details = [...flagged.map(note => `Claim flagged: ${note}`), ...notes];
  content.insertAdjacentHTML('beforeend', `<section class="grounding-qa"><h4>Final draft QA - Stage 7</h4><div class="qa-check-grid">${checks.map(([label, value]) => `<span><small>${escapeHtml(label)}</small><strong>${escapeHtml(String(value))}</strong></span>`).join('')}</div>${details.length ? `<ul>${details.map(note => `<li>${escapeHtml(note)}</li>`).join('')}</ul>` : '<p>No QA notes were returned.</p>'}</section>`);
}

// S0 Person Clarification & Resolved Prospect Helpers
function handlePersonClarificationNeeded(payload) {
  stopTimer();
  const card = document.getElementById('s0-clarification-card');
  if (!card) return;
  card.classList.remove('hidden');

  const statusTag = document.getElementById('active-status-tag');
  if (statusTag) statusTag.textContent = 'Status: ACTION REQUIRED (CONFIRM PROSPECT)';

  setTimeout(() => {
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 100);

  const conf = payload.confidence || 0.0;
  const meterFill = document.getElementById('s0-confidence-meter-fill');
  if (meterFill) {
    meterFill.style.width = `${Math.min(conf * 100, 100)}%`;
  }

  const list = document.getElementById('s0-candidates-list');
  if (!list) return;
  list.innerHTML = '';

  (payload.candidates || []).forEach(c => {
    const cEl = document.createElement('div');
    cEl.className = 'candidate-card';
    cEl.style.borderLeft = '3px solid #F59E0B';
    cEl.innerHTML = `
      <div>
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
          <h4>${escapeHtml(c.name)}</h4>
          <span class="candidate-score-badge" style="background: rgba(245, 158, 11, 0.2); color: #FBBF24;">${(c.final_score * 100).toFixed(0)}% Match</span>
        </div>
        <div style="font-size: 0.88rem; font-weight: 600; color: #60A5FA; margin-top: 4px;">
          ${escapeHtml(c.title_raw || c.title_normalized || 'Role unspecified')} at ${escapeHtml(c.company_raw || 'Company unspecified')}
        </div>
        <div style="font-size: 0.78rem; color: #94A3B8; margin-top: 4px;">
          Function: <strong style="color: #E2E8F0;">${escapeHtml(c.function || 'General')}</strong> (${escapeHtml(c.seniority || 'IC')})
          ${c.location ? `• 📍 ${escapeHtml(c.location)}` : ''}
        </div>
        ${c.source_url ? `
          <div style="font-size: 0.74rem; color: #38BDF8; margin-top: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            <a href="${escapeHtml(c.source_url)}" target="_blank" rel="noreferrer" style="color: #38BDF8; text-decoration: underline;">🔗 ${escapeHtml(c.source_url)}</a>
          </div>
        ` : ''}
      </div>
      <button type="button" class="btn btn-secondary btn-confirm-person" style="margin-top: 10px; font-size: 0.8rem;">
        ✓ Confirm This Prospect
      </button>
    `;

    const btn = cEl.querySelector('.btn-confirm-person');
    if (btn) {
      btn.addEventListener('click', () => {
        confirmPersonCandidate(c.name, c.company_raw || '', c.title_raw || c.title_normalized || '');
      });
    }

    list.appendChild(cEl);
  });
}

async function confirmPersonCandidate(name, company, title) {
  if (!currentRunId) return;
  try {
    const card = document.getElementById('s0-clarification-card');
    if (card) card.classList.add('hidden');
    startTimer();
    appendLog('s0_person', `Explicitly confirmed candidate: ${name} (${title} at ${company})`);
    
    await fetch(`/api/runs/${currentRunId}/clarify-person`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        selected_person_name: name,
        selected_company: company,
        selected_title: title
      })
    });
  } catch (err) {
    alert(`Failed to confirm prospect: ${err.message}`);
  }
}

async function submitPersonRefinement() {
  if (!currentRunId) return;
  const input = document.getElementById('s0-refine-input');
  const txt = input ? input.value.trim() : '';
  if (!txt) return;

  try {
    appendLog('s0_person', `Refining candidate search with hint: '${txt}'...`);
    await fetch(`/api/runs/${currentRunId}/clarify-person`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        refinement_text: txt
      })
    });
    if (input) input.value = '';
  } catch (err) {
    alert(`Failed to refine prospect: ${err.message}`);
  }
}

async function submitManualPerson() {
  if (!currentRunId) return;
  const comp = (document.getElementById('s0-manual-company')?.value || '').trim();
  const role = (document.getElementById('s0-manual-role')?.value || '').trim();
  if (!comp || !role) {
    alert('Please enter both Company and Role to proceed manually.');
    return;
  }

  try {
    const card = document.getElementById('s0-clarification-card');
    if (card) card.classList.add('hidden');
    startTimer();
    appendLog('s0_person', `Manually provided employer '${comp}' and role '${role}'.`);
    
    await fetch(`/api/runs/${currentRunId}/clarify-person`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        manual_company: comp,
        manual_role: role
      })
    });
  } catch (err) {
    alert(`Failed to set manual prospect: ${err.message}`);
  }
}

function handlePersonResolved(profile) {
  if (!profile) return;
  const s0Card = document.getElementById('s0-clarification-card');
  if (s0Card) s0Card.classList.add('hidden');

  const panel = document.getElementById('resolved-prospect-panel');
  if (!panel) return;

  const nameEl = document.getElementById('panel-prospect-name');
  if (nameEl) nameEl.textContent = profile.name || 'Prospect';
  const subEl = document.getElementById('panel-prospect-subtitle');
  if (subEl) subEl.textContent = `${profile.title_normalized || profile.title_raw || 'Executive'} at ${profile.company_raw}`;
  const compEl = document.getElementById('panel-company-val');
  if (compEl) compEl.textContent = profile.company_raw || '-';
  const titleEl = document.getElementById('panel-title-val');
  if (titleEl) titleEl.textContent = profile.title_normalized || profile.title_raw || '-';
  const funcEl = document.getElementById('panel-function-val');
  if (funcEl) funcEl.textContent = profile.function || 'Executive/GM';
  const senEl = document.getElementById('panel-seniority-val');
  if (senEl) senEl.textContent = (profile.seniority || 'C-level').replace(/_/g, ' ');
  const srcEl = document.getElementById('panel-source-val');
  if (srcEl) srcEl.textContent = profile.role_source === 'manual' ? 'Manual Entry' : 'Public Web';

  const confBadge = document.getElementById('panel-prospect-conf-badge');
  if (confBadge) {
    confBadge.textContent = `✓ Confirmed (${((profile.confidence || 1.0) * 100).toFixed(0)}%)`;
  }

  const linksContainer = document.getElementById('panel-links-list');
  if (linksContainer && profile.evidence_urls && profile.evidence_urls.length > 0) {
    linksContainer.innerHTML = profile.evidence_urls.map(u => {
      let host = u;
      try { host = new URL(u).hostname; } catch(e) {}
      return `<a href="${escapeHtml(u)}" target="_blank" rel="noreferrer" style="color: #38BDF8; margin-right: 8px; text-decoration: underline;">🔗 ${escapeHtml(host)}</a>`;
    }).join('');
  } else if (linksContainer) {
    linksContainer.textContent = profile.role_source === 'manual' ? 'Manually specified by SDR' : 'Corroborated by search index';
  }

  // Pre-fill override inputs
  const nameInp = document.getElementById('override-name-input');
  if (nameInp) nameInp.value = profile.name || '';
  const compInp = document.getElementById('override-company-input');
  if (compInp) compInp.value = profile.company_raw || '';
  const roleInp = document.getElementById('override-role-input');
  if (roleInp) roleInp.value = profile.title_normalized || profile.title_raw || '';

  panel.classList.remove('hidden');
}

function toggleEditProspectPanel() {
  const drawer = document.getElementById('edit-prospect-drawer');
  if (drawer) {
    drawer.classList.toggle('hidden');
  }
}

async function submitProspectOverride() {
  if (!currentRunId) return;
  const name = document.getElementById('override-name-input')?.value.trim();
  const company = document.getElementById('override-company-input')?.value.trim();
  const role = document.getElementById('override-role-input')?.value.trim();

  try {
    appendLog('s8_persist', `Overriding prospect: name='${name}', company='${company}', role='${role}'`);
    toggleEditProspectPanel();
    startTimer();

    await fetch(`/api/runs/${currentRunId}/override-prospect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name_override: name,
        company_override: company,
        title_override: role,
        role_override: role
      })
    });
  } catch (err) {
    alert(`Failed to update prospect: ${err.message}`);
  }
}

// Clarification handling (S1 Multi-Round Gate)
function handleClarificationNeeded(payload) {
  stopTimer();
  const card = document.getElementById('clarification-card');
  card.classList.remove('hidden');
  
  const conf = payload.confidence || 0.0;
  const round = payload.round || 1;
  
  document.getElementById('clarify-confidence').textContent = conf.toFixed(2);
  const roundBadge = document.getElementById('clarify-round-badge');
  if (roundBadge) roundBadge.textContent = `Round ${round}`;

  const meterFill = document.getElementById('confidence-meter-fill');
  if (meterFill) {
    meterFill.style.width = `${Math.min(conf * 100, 100)}%`;
  }

  const evalStatus = document.getElementById('clarify-eval-status');
  if (evalStatus) evalStatus.classList.add('hidden');

  // Candidate Cards
  const list = document.getElementById('candidates-list');
  list.innerHTML = '';
  (payload.candidates || []).forEach(c => {
    const cEl = document.createElement('div');
    cEl.className = 'candidate-card';
    cEl.innerHTML = `
      <div>
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
          <h4>${escapeHtml(c.name)}</h4>
          <span class="candidate-score-badge">${(c.final_score * 100).toFixed(0)}% Match</span>
        </div>
        <div class="candidate-domain">${escapeHtml(c.domain)}</div>
        <div style="font-size: 0.78rem; color: #60A5FA; margin-top: 4px;">
          ${escapeHtml(c.industry || 'Industry unspecified')} ${c.hq ? `• ${escapeHtml(c.hq)}` : ''}
        </div>
        <div style="font-size: 0.8rem; color: #9CA3AF; margin-top: 6px;">
          ${escapeHtml(c.description || 'No description available')}
        </div>
        ${c.distinguishing_fact ? `<div style="font-size: 0.75rem; color: #FCD34D; margin-top: 4px; font-style: italic;">Note: ${escapeHtml(c.distinguishing_fact)}</div>` : ''}
      </div>
      <button type="button" class="btn btn-secondary" style="margin-top: 10px; font-size: 0.8rem;" onclick="selectCandidate('${escapeHtml(c.domain)}')">
        ✓ Confirm This Entity
      </button>
    `;
    list.appendChild(cEl);
  });

  // Questions
  const qList = document.getElementById('clarify-questions-list');
  qList.innerHTML = '';
  if (payload.questions && payload.questions.length) {
    payload.questions.forEach((q, i) => {
      const qDiv = document.createElement('div');
      qDiv.style.marginBottom = '10px';
      qDiv.innerHTML = `
        <label style="font-size: 0.88rem; font-weight: 600; color: #F3F4F6; display: block; margin-bottom: 4px;">${escapeHtml(q)}</label>
        <input type="text" id="clarify_q_${i}" class="clarify-input" placeholder="Type your answer here..." style="width: 100%;" autocomplete="off" />
      `;
      qList.appendChild(qDiv);
      // Focus first input
      setTimeout(() => {
        const inp = document.getElementById(`clarify_q_${i}`);
        if (inp && i === 0) inp.focus();
      }, 100);
    });
  }
}

async function selectCandidate(domain) {
  try {
    const res = await fetch(`/api/runs/${currentRunId}/clarify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected_domain: domain })
    });
  } catch (err) {
    alert(`Clarification error: ${err.message}`);
  }
}

function confirmDirectWebsite() {
  const urlVal = document.getElementById('direct-website-input').value.trim();
  if (!urlVal) return;
  const cleanDomain = urlVal.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0];
  selectCandidate(cleanDomain);
}

async function sendClarification(answers, noneOfThese = false) {
  if (!currentRunId) {
    alert('No active run selected.');
    return;
  }
  const evalStatus = document.getElementById('clarify-eval-status');
  if (evalStatus) {
    evalStatus.textContent = noneOfThese ? 'Searching web for refined entity...' : 'Re-scoring candidate probabilities...';
    evalStatus.classList.remove('hidden');
  }

  try {
    const res = await fetch(`/api/runs/${currentRunId}/clarify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        none_of_these: Boolean(noneOfThese),
        answers: answers
      })
    });
    if (!res.ok) {
      const err = await res.json();
      alert(`Error submitting clarification: ${err.detail || 'Failed'}`);
      if (evalStatus) evalStatus.classList.add('hidden');
    }
  } catch (err) {
    alert(`Clarification error: ${err.message}`);
    if (evalStatus) evalStatus.classList.add('hidden');
  }
}

document.getElementById('submit-answers-btn').addEventListener('click', async () => {
  const ans = {};
  const inputs = document.querySelectorAll('#clarify-questions-list .clarify-input');
  let hasVal = false;
  inputs.forEach((inp, idx) => {
    if (inp.value.trim()) {
      ans[`q_${idx}`] = inp.value.trim();
      hasVal = true;
    }
  });

  if (!hasVal) {
    alert('Please enter an answer to clarify the company identity.');
    return;
  }

  await sendClarification(ans, false);
});

window.handleNoneOfThese = function() {
  const box = document.getElementById('none-of-these-box');
  if (box) {
    box.classList.toggle('hidden');
    if (!box.classList.contains('hidden')) {
      const inp = document.getElementById('none-of-these-input');
      if (inp) {
        // Pre-fill from question box if user already typed there
        const clarifyInp = document.querySelector('#clarify-questions-list .clarify-input');
        if (clarifyInp && clarifyInp.value.trim() && !inp.value.trim()) {
          inp.value = clarifyInp.value.trim();
        }
        inp.focus();
      }
    }
    return;
  }
  // Fallback to prompt if inline box not present
  const val = prompt("Target not listed? Enter the specific company name or domain (e.g. 'Mahalaxmi Travels'):");
  if (val && val.trim()) {
    sendClarification({ refinement: val.trim() }, true);
  }
};

window.submitRefinedSearch = async function() {
  const inp = document.getElementById('none-of-these-input');
  const val = inp ? inp.value.trim() : '';
  if (!val) {
    alert('Please enter the target company name or domain (e.g. Mahalaxmi Travels).');
    return;
  }
  await sendClarification({ refinement: val }, true);
};

// Enter key support for refined search box
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target && e.target.id === 'none-of-these-input') {
    window.submitRefinedSearch();
  }
});

// Human Review Handlers
async function handleReview(status) {
  if (!currentDraftId) {
    alert('No draft to review yet.');
    return;
  }
  const bodyText = document.getElementById('draft-body-editable').innerText;
  try {
    const res = await fetch(`/api/drafts/${currentDraftId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status: status,
        reviewer_edits: status === 'edited' ? bodyText : null,
        reason: `Human review marked as ${status}`
      })
    });
    if (res.ok) {
      const feedback = document.getElementById('review-feedback');
      feedback.textContent = `Draft ${status.toUpperCase()} recorded into audit log.`;
      feedback.classList.remove('hidden');
    }
  } catch (err) {
    alert(`Review submission failed: ${err.message}`);
  }
}

// Dashboard Loader
async function loadDashboard() {
  try {
    const res = await fetch('/api/runs');
    const data = await res.json();
    const runs = data.runs || [];

    // Stats
    document.getElementById('stat-total-runs').textContent = runs.length;
    const completed = runs.filter(r => r.duration);
    if (completed.length) {
      const avg = completed.reduce((a, b) => a + b.duration, 0) / completed.length;
      document.getElementById('stat-avg-duration').textContent = `${avg.toFixed(1)}s`;
    }
    const approved = runs.filter(r => r.status === 'approved' || r.status === 'edited').length;
    document.getElementById('stat-approval-rate').textContent = runs.length ? `${((approved / runs.length) * 100).toFixed(0)}%` : '0%';
    const autoConf = runs.filter(r => r.confirmation_method === 'auto').length;
    document.getElementById('stat-auto-confirmed').textContent = runs.length ? `${((autoConf / runs.length) * 100).toFixed(0)}%` : '0%';

    // Table
    const tbody = document.getElementById('runs-table-body');
    tbody.innerHTML = '';
    if (!runs.length) {
      tbody.innerHTML = '<tr><td colspan="10" class="text-center">No runs executed yet.</td></tr>';
      return;
    }

    runs.forEach(r => {
      const tr = document.createElement('tr');
      const roleText = r.recipient_title ? `${escapeHtml(r.recipient_title)} (${escapeHtml(r.recipient_lens || 'broad')})` : '<span style="color: #6B7280;">Company-level</span>';
      const fallbackBadge = r.fallback_banner_used ? '<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #F87171; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px;">⚠️ Fallback</span>' : '<span style="color: #6B7280;">-</span>';

      tr.innerHTML = `
        <td style="font-family: var(--font-mono); font-size: 0.75rem;">${r.id}</td>
        <td><strong>${escapeHtml(r.company_input)}</strong></td>
        <td style="font-size: 0.78rem;">${roleText}</td>
        <td><span class="status-badge badge-${r.status}">${r.status}</span></td>
        <td>${(r.confidence || 0).toFixed(2)}</td>
        <td>${r.duration ? `${r.duration.toFixed(1)}s` : '-'}</td>
        <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${r.selected_hypothesis_id || '-'}</td>
        <td style="text-align: center;">${fallbackBadge}</td>
        <td>${r.status}</td>
        <td><button class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.75rem;" onclick="viewPastRun('${r.id}')">View</button></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to load dashboard:', err);
  }
}

// Re-render past run
async function viewPastRun(runId) {
  try {
    const res = await fetch(`/api/runs/${runId}`);
    const data = await res.json();
    currentRunId = runId;
    usageRecords.length = 0;
    researcherActivity.clear();
    const processGrid = document.getElementById('researcher-process-grid');
    if (processGrid) processGrid.innerHTML = '<div class="process-placeholder">Loading saved researcher activity…</div>';
    const breakdown = document.getElementById('usage-breakdown');
    if (breakdown) breakdown.textContent = 'Loading saved model usage…';
    const usageTotal = document.getElementById('usage-total');
    if (usageTotal) usageTotal.textContent = '0 tokens';
    
    // Switch to tab
    document.querySelector('[data-tab="live-run"]').click();
    resetLiveWorkspace(data.run.company_input);
    if (data.last_event_id) {
      highestEventId = data.last_event_id;
    }
    document.getElementById('active-status-tag').textContent = `Status: ${data.run.status.toUpperCase()}`;
    if (data.run.duration) {
      document.getElementById('live-timer').textContent = `${data.run.duration.toFixed(1)}s`;
    }

    // Company Profile
    if (data.run.company_profile) {
      renderCompanyProfile(data.run.company_profile, data.run.confirmed_company ? data.run.confirmed_company.name : data.run.company_input);
    }

    // Check if run is awaiting person clarification
    if (data.run.status === 'awaiting_person_clarification' && data.run.person_profile) {
      let prof = data.run.person_profile;
      if (typeof prof === 'string') {
        try { prof = JSON.parse(prof); } catch(e) {}
      }
      if (prof) {
        handlePersonClarificationNeeded({
          confidence: prof.confidence || data.run.person_confidence,
          person_name: prof.name || data.run.person_name,
          candidates: prof.alternatives || [],
          questions: prof.clarification_questions || []
        });
      }
    }

    // Role chip & fallback banner restoration
    if (data.run.recipient_title) {
      updateRoleChipUI({
        title: data.run.recipient_title,
        recipient_title: data.run.recipient_title,
        recipient_name: data.run.recipient_name,
        lens: data.run.recipient_lens,
        seniority: data.run.seniority,
        role_unrecognized: false
      });
    }
    if (data.run.fallback_banner_used) {
      let suggestions = [];
      try { suggestions = JSON.parse(data.run.fallback_suggestions || '[]'); } catch(e) {}
      showFallbackBanner({
        fallback_banner_used: true,
        suggested_roles: suggestions
      });
    }

    // Populate evidence
    if (data.evidence) {
      data.evidence.forEach(e => appendEvidence(e));
    }
    if (data.llm_usage) {
      data.llm_usage.forEach(row => appendUsageRecord(row));
    }
    if (data.research_activity) {
      data.research_activity.forEach(renderResearcherActivity);
      if (!data.research_activity.length && processGrid) {
        processGrid.innerHTML = '<div class="process-placeholder">No researcher activity was saved for this run.</div>';
      }
    }
    // Hypotheses
    if (data.hypotheses) {
      renderHypotheses(data.hypotheses, data.run.selected_hypothesis_id);
      renderGroundingWork(data.hypotheses);
    }
    // Solution
    if (data.solution) {
      renderSolution(data.solution);
    }
    // Draft
    if (data.draft) {
      renderDraft(data.draft);
      if (data.draft.quality_report) {
        renderQualityReport(data.draft.quality_report, data.draft);
      }
    }
    setStepperStage('s7', true);
  } catch (err) {
    alert(`Could not load past run: ${err.message}`);
  }
}

// Assumptions loader
async function loadAssumptions() {
  try {
    const res = await fetch('/api/assumptions');
    const data = await res.json();
    const tbody = document.getElementById('assumptions-table-body');
    tbody.innerHTML = '';
    (data.assumptions || []).forEach(a => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="assumption-number">#${escapeHtml(a.num)}</td>
        <td class="assumption-decision">${escapeHtml(a.decision)}</td>
        <td class="assumption-why">${escapeHtml(a.why)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Assumptions load error:', err);
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Approach-page scenarios return here with a case ID and prefill the workspace.
const initialPageParams = new URLSearchParams(window.location.search);
const requestedDemoCase = initialPageParams.get('demo_case');
const requestedTab = initialPageParams.get('tab');
if (requestedDemoCase) {
  window.history.replaceState({}, document.title, window.location.pathname);
  requestAnimationFrame(() => loadDemoCase(requestedDemoCase));
} else if (['live-run', 'dashboard', 'assumptions'].includes(requestedTab)) {
  document.querySelector(`[data-tab="${requestedTab}"]`)?.click();
}
