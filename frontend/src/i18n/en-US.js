export default {
  nav: {
    home: 'Home',
    workspace: 'Workspace',
    learn: 'Learn',
    about: 'About',
    report: 'Reporting',
    godView: 'God View',
    settings: 'Settings',
  },
  godView: {
    header: {
      terminal: 'GOD VIEW TERMINAL',
      selectSession: '-- Select Session --',
      loading: 'LOADING...',
      refresh: 'REFRESH',
      autoOn: 'AUTO ON',
      autoOff: 'AUTO OFF',
      autoDelayed: 'AUTO (DELAYED)'
    },
    status: {
      signals: 'SIGNALS',
      active: 'active',
      buyYes: 'BUY YES',
      buyNo: 'BUY NO',
      hold: 'HOLD',
      contracts: 'CONTRACTS',
      lastRefreshed: 'Last'
    },
    tabs: {
      main: 'Market Signals',
      ensemble: 'Ensemble Pred',
      scenarios: 'Scenario Comparison',
      sentiment: 'Sentiment Heatmap'
    },
    panels: {
      contracts: {
        title: 'POLYMARKET CONTRACTS',
        loading: 'Fetching contracts...',
        empty: 'No contracts matched for this session.'
      },
      signals: {
        title: 'TRADING SIGNALS',
        loading: 'Computing signals from agent consensus...',
        empty: 'No signals generated yet. Ensure simulation has completed at least 5 rounds.'
      },
      consensus: {
        title: 'AGENT CONSENSUS',
        sentimentTrend: 'SENTIMENT TREND',
        signalBreakdown: 'SIGNAL BREAKDOWN',
        recentDecisions: 'RECENT DECISIONS',
        noData: 'No data',
        awaiting: 'Awaiting agent decisions...'
      },
      feed: {
        title: 'LIVE AGENT FEED',
        empty: 'No agent activity yet.',
        posts: 'posts'
      }
    },
    placeholders: {
      selectSession: 'Select a simulation session to begin',
      godViewDesc: 'The God View Terminal shows real-time Polymarket trading signals derived from agent consensus'
    }
  },
  interaction: {
    welcome: 'Welcome to Deep Interaction mode. You can ask questions about the report or chat with individual agents.',
    noResponse: '(No response)',
    sendFailed: 'Send failed:',
    settings: {
      title: 'Chat Settings',
      target: 'Chat Target',
      analyst: 'Report Analyst',
      agent: 'Specific Agent',
      selectAgent: 'Select Agent',
      selectPlaceholder: 'Please select...',
      whatIf: 'What-If Parameters',
      whatIfHint: 'Describe hypothetical scenarios in your chat, e.g., "What if unemployment rises to 8%"'
    },
    chat: {
      you: 'You',
      ai: 'AI',
      system: 'System',
      error: 'Error',
      placeholder: 'Type your question...',
      sending: 'Sending...',
      send: 'Send'
    }
  },
  lessons: {
    overview: {
      traditional: {
        title: 'Traditional Polling',
        points: [
          'Ask 1,000 people their thoughts',
          'Static snapshot — one-time',
          'Ignores social impact',
          'Cannot simulate policy changes'
        ],
        verdict: 'Limited'
      },
      murmura: {
        title: 'Murmura',
        points: [
          'Simulate 500 AI agent interactions',
          'Dynamic evolution — 30+ rounds',
          'Echo Chamber + Trust Networks',
          'Real-time policy shock injection'
        ],
        verdict: 'Emergent Prediction'
      },
      text1: 'Murmura does not ask people "what are you thinking," but uses AI agents to simulate real social interaction processes. Each agent has its own personality, memory, and trust circle; they influence each other, and eventually, group trends <strong>emerge</strong>.',
      text2: 'The metrics we track include: property price confidence, migration intent, consumption patterns, political polarization, etc.'
    },
    uncertainty: {
      intro: "Murmura's prediction uncertainty comes from four main sources. Click each source to learn more:",
      closing: 'Transparently presenting uncertainty is a core principle of responsible AI prediction. Murmura is not an "oracle" but a tool to help think about multiple possible futures.',
      sources: {
        behavior: { label: 'Agent Behavior Randomness', detail: 'Each AI agent\'s LLM decision has inherent randomness that cannot be fully controlled.' },
        macro: { label: 'Macro Data Error', detail: 'Macro data like GDP and unemployment rates have measurement errors and revisions, directly affecting initial conditions.' },
        model: { label: 'Model Structure Assumptions', detail: 'Parameters like consumption functions and trust decay rates are estimated from calibration data, which have statistical uncertainty.' },
        shocks: { label: 'External Shocks Unpredictability', detail: 'Exogenous shocks like geopolitical events and natural disasters cannot be included in the model in advance.' }
      }
    },
    kg: {
      intro: 'Knowledge Graphs break down complex issues into <strong>entities</strong> (nodes) and <strong>relationships</strong> (edges). Hover over nodes to see descriptions.',
      closing: 'During simulation, agent actions update the edge weights on the graph — reflecting changes in the strength of causal relationships.',
      types: {
        economic: 'Economic',
        person: 'Person',
        policy: 'Policy',
        organization: 'Organization',
        social: 'Social',
        location: 'Location'
      },
      nodes: {
        hibor: 'HIBOR Rate',
        mortgage: 'Mortgage Rate',
        prices: 'Property Indices',
        buyers: 'First-time Buyers',
        tax: 'Stamp Duty',
        bank: 'HSBC',
        hardlife: 'Affordability',
        migration: 'Migration Wave',
        shatin: 'Sha Tin',
        fed: 'The Fed'
      }
    },
    boids: {
      intro: 'Agent behavior follows three simple rules, similar to bird flocking (Boids theory):',
      rules: {
        alignment: { title: 'Alignment', desc: 'Heading in the same direction as neighbors (Social Consensus).' },
        cohesion: { title: 'Cohesion', desc: 'Moving towards the average position of neighbors (Trust Building).' },
        separation: { title: 'Separation', desc: 'Avoiding getting too close to conflicting entities (Echo Chambers).' }
      },
      closing: 'No single bird has the concept of a "flock formation" — yet the formation emerges naturally. This is <strong>emergence</strong>.',
      murmura: 'Murmura works the same way — each agent makes decisions based on its own personality and memory, but overall, predictable social trends emerge.'
    },
    ner: {
      intro: 'Each piece of seed text undergoes the following processing pipeline, eventually becoming nodes and edges in the Knowledge Graph:',
      steps: ['Raw Text', 'Tokenization', 'NER Recognition', 'Relation Extraction', 'KG Node'],
      example: {
        label: 'Example:',
        text: 'The <strong>Fed</strong> announced a <strong>rate hike</strong> of 0.25%, affecting the <strong>HK property market</strong>',
        org: 'Fed (Org)',
        hike: 'Rate Hike (Event)',
        market: 'HK Property (Economic)',
        announced: 'announced',
        affecting: 'affecting'
      },
      closing: 'This process is driven by DeepSeek V3.2, automatically identifying entity types and causal relationships to build a structured knowledge representation.'
    },
    shocks: {
      intro: 'Policy shocks are the "stress tests" of the Murmura system. You can inject the following events into the running simulation:',
      events: {
        interest_rate: { title: 'Interest Rate Hike', desc: 'Sudden 1% increase in mortgage rates' },
        tax: { title: 'Stamp Duty Remove', desc: 'Government removes all property stamp duties' },
        immigration: { title: 'Migration Policy Change', desc: 'New points-based immigration system launched' }
      },
      text: 'When a shock is injected, agents re-evaluate their beliefs and trust networks, leading to a "cascade" effect throughout the entire system.'
    },
    percentiles: {
      intro: 'Murmura does not just output a single prediction line, but an entire probability distribution. Drag the slider to adjust scenario intensity:',
      chartLabel: 'Property Price Confidence Index Forecast',
      mild: 'Mild Shock',
      extreme: 'Extreme Shock',
      intensity: 'Scenario Intensity',
      p10_90: 'p10–p90',
      p25_75: 'p25–p75',
      p50: 'p50 (Median)',
      quiz: {
        q1: 'Question 1: What does p50 represent?',
        q1_opts: [
          { value: 'p50', label: 'Median Forecast' },
          { value: 'avg', label: 'Average' },
          { value: 'best', label: 'Best Case' }
        ],
        q1_correct: 'Correct! p50 is the median; half of the simulation results are higher and half are lower.',
        q1_wrong: 'Incorrect. p50 is the median (50th percentile), not the average.',
        q2: 'Question 2: What does a wider p10-p90 interval represent?',
        q2_opts: [
          { value: 'wide', label: 'Higher Uncertainty' },
          { value: 'certain', label: 'More Accurate' },
          { value: 'same', label: 'Same Results' }
        ],
        q2_correct: 'Correct! A wider interval reflects higher prediction uncertainty.',
        q2_wrong: 'Incorrect. A wider interval means higher uncertainty, not more accuracy.'
      }
    },
    challenges: {
      intro: 'Simulation results should not be accepted blindly. Here is a 5-step critical assessment checklist — check each step as you complete it:',
      allChecked: 'All complete! You have mastered the method of critical model assessment.',
      reset: 'Reset',
      closing: 'Developing these 5 habits will help you avoid over-reliance on model outputs and make more informed judgments.',
      assumptions: { label: 'Check Assumptions', detail: 'Are the model\'s premises reasonable?' },
      history: { label: 'Compare History', detail: 'How did similar situations play out in the past?' },
      boundary: { label: 'Boundary Test', detail: 'What happens with extreme parameters?' },
      counterfactual: { label: 'Counterfactual Reasoning', detail: 'How would results change if a factor was removed?' },
      omission: { label: 'Find Omissions', detail: 'Are there any critical factors missing?' }
    },
    mistakes: {
      intro: 'Avoid these common pitfalls when interpreting Murmura simulations:',
      list: [
        { wrong: 'The model says 70% chance of falling, so it will definitely fall', correct: 'A 70% chance means it happens about 7 times out of 10' },
        { wrong: 'p50 prediction is the most accurate', correct: 'p50 is the median; real results may fall anywhere between p10-p90' },
        { wrong: 'The more agents, the more accurate', correct: 'Agent diversity is more important than quantity' },
        { wrong: 'The model predicted a Black Swan event', correct: 'Models can only capture known risks; true Black Swans are unpredictable' },
        { wrong: 'Different results for two simulations mean the model is unreliable', correct: 'Randomness is a feature of the model, not a flaw' }
      ]
    },
    dataSources: {
      intro: 'Murmura combines high-frequency market data with low-frequency statistical indicators to ground its simulations:',
      category: 'Category',
      items: 'Key Items',
      frequency: 'Frequency',
      lag: 'Data Lag',
      gov: { category: 'Gov Statistics', items: ['Census', 'Employment', 'Retail Sales'], frequency: 'Monthly', lag: '~2 months' },
      finance: { category: 'Financial Markets', items: ['HSI Index', 'Sector Indices', 'Volume'], frequency: 'Real-time', lag: '< 15 mins' },
      rates: { category: 'Interest Rates', items: ['HIBOR', 'Fed Rate', 'USD/HKD'], frequency: 'Daily', lag: '1 day' },
      social: { category: 'Social Media', items: ['RTHK News', 'Forum Posts', 'Sentiment'], frequency: 'Hourly', lag: '< 1 hour' },
      macro: { category: 'Macro Economy', items: ['China GDP', 'CPI', 'Exports'], frequency: 'Quarterly', lag: '~3 months' }
    },
    meta: {
      t0: 'What does system predict?',
      t1: 'What is Emergence?',
      t2: 'KG Introduction',
      t3: 'From Evidence to Structure',
      t4: 'From Scenario to Outcome',
      t5: 'Reading Probabilities',
      t6: 'Confidence & Uncertainty',
      t7: 'Challenging the Model',
      t8: 'Common Mistakes',
      t9: 'Data Sources & Limits'
    }
  },
  learn: {
    subtitle: 'Learn the principles behind Murmura'
  },
  workspace: {
    title: 'Workspace',
    subtitle: 'All prediction simulation sessions',
    adminBtn: 'Performance',
    newBtn: '+ New Prediction',
    loading: 'Loading sessions...',
    retry: 'Retry',
    empty: {
      title: 'No Predictions Yet',
      description: 'Create your first social simulation'
    },
    status: {
      completed: 'Completed',
      running: 'Running',
      failed: 'Failed',
      pending: 'Pending',
      created: 'Created'
    },
    meta: {
      agents: 'agents',
      rounds: 'rounds'
    },
    evidence: 'Evidence Search',
    loadMore: 'Load More'
  },
  home: {
    subtitle: 'Universal Prediction Engine',
    description: 'Drop any seed text — news, fiction, geopolitical events — AI auto-builds the world, spawns agents, and starts simulation. Combines Multi-Agent Systems, Knowledge Graphs, and Macro Forecasting to foresee collective behavior.',
    startTitle: 'Start Predicting Now',
    startSubtitle: 'Upload a document or enter seed text, AI handles the rest',
    dropLabel: 'Drop file here, or click to browse',
    dropHint: 'Supports PDF, TXT, Markdown · Max 10 MB',
    or: 'OR',
    textareaPlaceholder: 'Enter scenario description, e.g. Fed announces 200bps rate hike, global markets panic sell...',
    questionPlaceholder: '(Optional) What do you want to predict? e.g. Which faction will dominate? How will social sentiment evolve?',
    launchBtn: 'One-Click Predict',
    launching: 'Launching...',
    customDomain: 'Custom Domain Pack',
    dataConnector: 'Data Connector',
    godView: 'God View',
    presets: {
      fast: 'Fast',
      fastHint: '100 agents · 15 rounds (~2 min)',
      standard: 'Standard',
      standardHint: '300 agents · 20 rounds (~8 min)',
      deep: 'Deep',
      deepHint: '500 agents · 30 rounds (~20 min)'
    },
    errors: {
      format: 'Support for {ext} format is not available. Please upload PDF, TXT, or Markdown.',
      size: 'File size exceeds unique 10 MB limit.',
      launch: 'Launch failed, please try again.'
    }
  },
  onboarding: {
    skip: 'Skip',
    next: 'Next',
    finish: 'Finish',
    steps: {
      scenario: { title: 'Select Scenario', desc: 'Choose a social issue from the home page as the starting point.' },
      graph: { title: 'Knowledge Graph', desc: 'The system automatically builds a KG to show causal relationships.' },
      simulation: { title: 'Run Simulation', desc: 'Observe how AI agents interact, decide, and form trends.' }
    }
  },
  landing: {
    nav: {
      howItWorks: 'How it works',
      features: 'Features',
      launch: 'Launch Engine →'
    },
    hero: {
      eyebrow: 'UNIVERSAL PREDICTION ENGINE',
      title: 'Drop any text.',
      titleAccent: 'Simulate any world.',
      sub: 'Feed Murmura a sentence, a document, or a scenario — it builds the knowledge graph, spawns agents, runs the simulation, and predicts collective outcomes.',
      cta: 'Start Predicting',
      workspace: 'Workspace',
      stats: {
        agents: 'Agents per run',
        macro: 'Macro indicators',
        monteCarlo: 'Monte Carlo trials',
        xai: 'XAI analysis tools'
      }
    },
    workflow: {
      label: 'HOW IT WORKS',
      title: '5-Step Workflow',
      steps: {
        graph: { label: 'GRAPH', title: 'Knowledge Graph', desc: 'Seed text → entity extraction → causal network auto-built' },
        env: { label: 'ENV', title: 'Environment Setup', desc: 'Agent factory generates profiles from KG nodes, zero config needed' },
        sim: { label: 'SIM', title: 'Simulation', desc: 'OASIS multi-agent engine runs with emergent behavior fully on' },
        report: { label: 'REPORT', title: 'ReACT Report', desc: '3-phase LLM: outline → per-section tool calls → markdown assembly' },
        interact: { label: 'INTERACT', title: 'Deep Interaction', desc: 'Interview agents, inject shocks, branch into What-If scenarios' }
      }
    },
    features: {
      label: 'CAPABILITIES',
      title: 'What the Engine Does',
      list: {
        universal: { title: 'Universal Mode', desc: 'Drop any seed text — news, fiction, geopolitics. Engine infers actors, decisions, metrics, shocks automatically.' },
        kg: { title: 'Knowledge Graph', desc: 'GraphRAG tracks entity relationships and causal chains. Snapshots every 5 rounds, evolves with each interaction.' },
        emergence: { title: 'Emergence Engine', desc: 'Faction formation, tipping points, echo chambers, virality cascades — all emergent, not scripted.' },
        monteCarlo: { title: 'Monte Carlo', desc: '100-trial LHS + t-Copula sampling. Wilson score confidence intervals. Up to 10,000 stochastic trials.' },
        macro: { title: 'Macro Feedback', desc: '11 macro indicators updated per round. Agent micro-decisions feed back into macro state in real time.' },
        scenarios: { title: 'Scenario Branches', desc: 'Fork any simulation at any round. Compare diverging timelines side by side.' }
      }
    },
    useCases: {
      label: 'USE CASES',
      title: 'Works on Any Domain',
      list: {
        geopolitics: { tag: 'Geopolitics', desc: 'Taiwan Strait escalation, Iran-Israel scenarios, trade war cascades' },
        finance: { tag: 'Finance', desc: 'Fed rate hike contagion, crypto market panics, corporate competition' },
        society: { tag: 'Society', desc: 'Policy impact modeling, social movement dynamics, demographic shifts' },
        fiction: { tag: 'Fiction', desc: 'Dream of the Red Chamber, Harry Potter, any narrative world' }
      }
    },
    cta: {
      label: 'READY TO SIMULATE?',
      title: 'Drop your first scenario',
      sub: 'No configuration needed. Paste any text and the engine handles the rest.',
      btn: 'Launch Engine →'
    },
    footer: {
      desc: 'Universal Prediction Engine · Agent-Based Simulation',
      copy: 'Built with FastAPI · Vue 3 · OASIS · LanceDB'
    }
  },
  process: {
    nav: {
      steps: {
        graph: { label: 'Graph Build', navLabel: 'GRAPH' },
        env: { label: 'Env Setup', navLabel: 'ENV' },
        sim: { label: 'Simulation', navLabel: 'SIM' },
        report: { label: 'Report Gen', navLabel: 'REPORT' },
        interact: { label: 'Interaction', navLabel: 'INTERACT' }
      },
      expressBadge: '⚡ Express Mode · Auto-configured'
    },
    errors: {
      graphFirst: 'Please complete Graph Build first',
      envFirst: 'Please complete Env Setup and start simulation',
      simFirst: 'Report can be generated after simulation completes',
      reportFirst: 'Please generate report first',
      engineUnavailable: 'Simulation engine unavailable — use Docker for full features'
    }
  },
  settings: {
    header: {
      title: 'Settings',
      subtitle: 'Manage API keys, model selection, and system preferences'
    },
    tabs: {
      api: {
        title: 'API Keys',
        desc: 'Configure API keys for LLM providers. Keys are stored encrypted and masked upon display.',
        empty: '— Not Set —',
        testing: '⏳ Testing...',
        test: 'Test',
        save: 'Save',
        verifying: '⏳ Verifying key...',
        connFailed: 'Connection failed'
      },
      model: {
        title: 'Model Selection',
        desc: 'Configure LLM models per workflow step. Changes apply immediately, no restart required.',
        quickApply: 'Quick apply:',
        globalFallback: 'Global Defaults (used when no per-step model is set)',
        steps: {
          useGlobal: 'Use global default',
          fillBoth: 'Please fill in both Provider and Model',
          step1: { label: 'Step 1: Knowledge Graph Build', hint: 'Recommend a fast model (e.g. deepseek-v3); called frequently during entity extraction' },
          step2: { label: 'Step 2: Environment Setup', hint: 'Recommend a strong reasoning model for agent profile generation and scenario analysis' },
          step3: { label: 'Step 3: Simulation Run', hint: 'Main model for key stakeholders; Lite model for background agents (saves cost)' },
          step4: { label: 'Step 4: Report Generation', hint: 'Recommend a long-form capable model (e.g. Gemini Pro, GPT-4o)' },
          step5: { label: 'Step 5: Interaction', hint: 'Recommend a conversational model for Interview Engine' },
        },
        agent: {
          title: 'Agent Decision LLM (Global)',
          providerHint: 'Provider used for agent thinking, decision-making, and interactions',
          main: 'Agent Model (Main)',
          mainHint: 'Stakeholder agents use this model',
          lite: 'Agent Model (Lite)',
          liteHint: 'Background agents use this cheaper model (optional)'
        },
        report: {
          title: 'Report Generation LLM (Global)',
          providerHint: 'LLM used for final reports, summaries, and chart analysis',
          model: 'Report Model',
          modelHint: 'Leave blank to use the provider\'s default model'
        }
      },
      sim: {
        title: 'Simulation Defaults',
        desc: 'Set default parameters for new simulations.',
        preset: 'Default Preset',
        agents: 'Default Agent Count',
        agentsUnit: 'agents',
        agentsHint: 'Default number of agents when creating a new simulation (5–500)',
        concurrency: 'Concurrency Limit',
        concurrencyHint: 'Max concurrent LLM requests. Recommended: 30–80',
        domain: 'Default Domain Pack',
        domainHint: 'Default Domain Pack ID applied to new simulations'
      },
      ui: {
        title: 'UI Preferences',
        desc: 'The following preferences are saved locally (localStorage) and apply immediately.',
        lang: 'UI Language',
        itemsPerPage: 'Items Per Page',
        autoOpen: 'Auto-open report after simulation',
        autoOpenHint: 'Automatically navigate to the Report page when simulation completes'
      },
      data: {
        title: 'Data Sources',
        desc: 'Configure external data source API keys and integration options.',
        empty: '— Not Set —',
        test: 'Test',
        save: 'Save',
        verifying: '⏳ Verifying...',
        ref: 'From',
        fred: 'FRED API Key',
        fredHint: 'From <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" rel="noopener">St. Louis Fed</a>, used for fetching macroeconomic data',
        externalFeed: 'Enable External Feeds',
        externalFeedHint: 'When enabled, the system periodically updates data from FRED, World Bank, etc.',
        refreshInterval: 'Refresh Interval',
        seconds: 'seconds',
        refreshHint: 'Interval between automatic updates (300–86400 seconds)'
      }
    }
  }
}
