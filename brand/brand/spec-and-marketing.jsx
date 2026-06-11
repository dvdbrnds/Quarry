/* Brand spec sheet + marketing one-pager for BirdDog */

// ============================================================
// BRAND SPEC SHEET
// ============================================================
const SpecSheet = () => {
  const Swatch = ({ name, hex, varName, dark }) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ width: '100%', height: 88, background: hex, borderRadius: 6, border: '1px solid rgba(0,0,0,0.06)' }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, letterSpacing: '0.16em', color: '#0a1428', textTransform: 'uppercase', fontWeight: 600 }}>{name}</div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, color: '#5a6373' }}>{hex}</div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, color: '#9099a8' }}>{varName}</div>
      </div>
    </div>
  );

  return (
    <div style={{ width: 1100, background: '#fafaf6', padding: 56, fontFamily: 'var(--bd-body)', color: '#0a1428' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', borderBottom: '2px solid #0a1428', paddingBottom: 24, marginBottom: 32 }}>
        <div>
          <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 11, letterSpacing: '0.34em', color: '#ca8a04', textTransform: 'uppercase', marginBottom: 8 }}>Brand Standards · v1.0</div>
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 56, fontWeight: 800, letterSpacing: '-0.04em', lineHeight: 0.95 }}>BirdDog</div>
          <div style={{ fontFamily: 'var(--bd-body)', fontSize: 14, color: '#5a6373', marginTop: 6 }}>Color, type, and mark specifications</div>
        </div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.28em', color: '#5a6373', textAlign: 'right', textTransform: 'uppercase' }}>
          Document BD-BS-001<br/>Issued · April 2026<br/>Patrol Suite
        </div>
      </div>

      {/* COLOR */}
      <SectionLabel n="01">Color System</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 16, marginBottom: 18 }}>
        <Swatch name="Navy 950" hex="#050b1a" varName="--bd-navy-950" />
        <Swatch name="Navy 900" hex="#0a1428" varName="--bd-navy-900" />
        <Swatch name="Navy 800" hex="#0f1d3a" varName="--bd-navy-800" />
        <Swatch name="Navy 700" hex="#14274d" varName="--bd-navy-700" />
        <Swatch name="Navy 600" hex="#1e3563" varName="--bd-navy-600" />
        <Swatch name="Navy 400" hex="#4a6aa8" varName="--bd-navy-400" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 16, marginBottom: 18 }}>
        <Swatch name="Brass 700" hex="#8a6a08" varName="--bd-brass-700" />
        <Swatch name="Brass 600" hex="#ca8a04" varName="--bd-brass-600" />
        <Swatch name="Brass 500" hex="#eab308" varName="--bd-brass-500" />
        <Swatch name="Brass 400" hex="#fbbf24" varName="--bd-brass-400" />
        <Swatch name="Brass 300" hex="#fcd34d" varName="--bd-brass-300" />
        <Swatch name="Bone 100" hex="#f3f1ea" varName="--bd-bone-100" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 16, marginBottom: 36 }}>
        <Swatch name="Ink 900" hex="#14171c" varName="--bd-ink-900" />
        <Swatch name="Ink 700" hex="#2d3340" varName="--bd-ink-700" />
        <Swatch name="Ink 500" hex="#5a6373" varName="--bd-ink-500" />
        <Swatch name="Ink 300" hex="#9099a8" varName="--bd-ink-300" />
        <Swatch name="Signal Red" hex="#b91c1c" varName="--bd-red" />
        <Swatch name="Signal Green" hex="#15803d" varName="--bd-green" />
      </div>

      {/* TYPE */}
      <SectionLabel n="02">Typography</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32, marginBottom: 36 }}>
        <div style={{ borderTop: '1px solid #c8c3b1', paddingTop: 16 }}>
          <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, letterSpacing: '0.28em', color: '#ca8a04', textTransform: 'uppercase', marginBottom: 12 }}>Display · Space Grotesk</div>
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 64, fontWeight: 800, letterSpacing: '-0.04em', lineHeight: 0.9 }}>Aa Bb Cc</div>
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 16, fontWeight: 700, marginTop: 12 }}>Headlines · Wordmark · Display</div>
          <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 11, color: '#5a6373', marginTop: 4 }}>Weights 400 / 600 / 700 / 800</div>
        </div>
        <div style={{ borderTop: '1px solid #c8c3b1', paddingTop: 16 }}>
          <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, letterSpacing: '0.28em', color: '#ca8a04', textTransform: 'uppercase', marginBottom: 12 }}>Body · Inter</div>
          <div style={{ fontFamily: 'var(--bd-body)', fontSize: 64, fontWeight: 500, letterSpacing: '-0.02em', lineHeight: 0.9 }}>Aa Bb Cc</div>
          <div style={{ fontFamily: 'var(--bd-body)', fontSize: 16, fontWeight: 500, marginTop: 12 }}>Body · UI · Form labels</div>
          <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 11, color: '#5a6373', marginTop: 4 }}>Weights 400 / 500 / 600 / 700</div>
        </div>
      </div>
      <div style={{ borderTop: '1px solid #c8c3b1', paddingTop: 16, marginBottom: 36 }}>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, letterSpacing: '0.28em', color: '#ca8a04', textTransform: 'uppercase', marginBottom: 12 }}>Mono · JetBrains Mono</div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 28, letterSpacing: '0.08em', fontWeight: 600 }}>PA-7B 4291 · STATUS: ACTIVE</div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 11, color: '#5a6373', marginTop: 8 }}>License plates · IDs · Timestamps · Code</div>
      </div>

      {/* USAGE RULES */}
      <SectionLabel n="03">Wordmark Usage</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 32 }}>
        <UsageBox label="✓ Primary on navy" bg="#0a1428">
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 32, fontWeight: 800, color: '#fafaf6', letterSpacing: '-0.03em' }}>BirdDog</div>
        </UsageBox>
        <UsageBox label="✓ Primary on bone" bg="#f3f1ea">
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 32, fontWeight: 800, color: '#0a1428', letterSpacing: '-0.03em' }}>BirdDog</div>
        </UsageBox>
        <UsageBox label="✓ Brass accent only on dark" bg="#0a1428">
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 32, fontWeight: 800, color: '#fafaf6', letterSpacing: '-0.03em' }}>Bird<span style={{ color: '#fbbf24' }}>Dog</span></div>
        </UsageBox>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 32 }}>
        <UsageBox label="✗ Do not stretch" bg="#f3f1ea" warn>
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 32, fontWeight: 800, color: '#0a1428', letterSpacing: '-0.03em', transform: 'scaleX(1.6)' }}>BirdDog</div>
        </UsageBox>
        <UsageBox label="✗ Do not use rainbow / unbranded color" bg="#f3f1ea" warn>
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 32, fontWeight: 800, letterSpacing: '-0.03em', background: 'linear-gradient(90deg, #ec4899, #06b6d4)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>BirdDog</div>
        </UsageBox>
        <UsageBox label="✗ Do not place on busy imagery" bg="repeating-linear-gradient(45deg, #fbbf24, #fbbf24 8px, #b91c1c 8px, #b91c1c 16px)" warn>
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 32, fontWeight: 800, color: '#0a1428', letterSpacing: '-0.03em' }}>BirdDog</div>
        </UsageBox>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #c8c3b1', paddingTop: 16, fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.24em', color: '#5a6373', textTransform: 'uppercase' }}>
        <span>BirdDog Patrol Suite</span>
        <span>Brand Standards · 1 of 1</span>
        <span>© 2026 · All Rights Reserved</span>
      </div>
    </div>
  );
};

const SectionLabel = ({ n, children }) => (
  <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 18 }}>
    <span style={{ fontFamily: 'var(--bd-mono)', fontSize: 11, letterSpacing: '0.3em', color: '#ca8a04' }}>{n}</span>
    <span style={{ fontFamily: 'var(--bd-display)', fontSize: 22, fontWeight: 700, letterSpacing: '-0.02em' }}>{children}</span>
    <div style={{ flex: 1, height: 1, background: '#c8c3b1' }} />
  </div>
);

const UsageBox = ({ children, label, bg, warn }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
    <div style={{ height: 100, background: bg, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', border: warn ? '1px solid rgba(185,28,28,0.2)' : '1px solid rgba(0,0,0,0.06)' }}>
      {children}
    </div>
    <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.2em', color: warn ? '#b91c1c' : '#15803d', textTransform: 'uppercase', fontWeight: 600 }}>{label}</div>
  </div>
);

// ============================================================
// MARKETING ONE-PAGER (for IT/procurement at other universities)
// ============================================================
const OnePager = () => (
  <div style={{ width: 1100, background: '#fafaf6', fontFamily: 'var(--bd-body)', color: '#0a1428' }}>
    {/* Hero */}
    <div style={{ background: '#0a1428', padding: '56px 56px 64px', position: 'relative', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 4, background: '#fbbf24' }} />
      <div style={{ position: 'absolute', top: 16, left: 0, right: 0, height: 1, background: 'rgba(251,191,36,0.4)' }} />
      <div style={{ position: 'absolute', right: 20, top: '50%', transform: 'translateY(-50%)', opacity: 0.5 }}>
        <img src="greyhound-brass.png" style={{ height: 320, width: 'auto', display: 'block' }} />
      </div>

      <div style={{ position: 'relative', zIndex: 1, display: 'flex', justifyContent: 'space-between', marginBottom: 56 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <img src="greyhound-brass.png" style={{ height: 36, width: 'auto', display: 'block' }} />
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 22, fontWeight: 800, color: '#fafaf6', letterSpacing: '-0.02em' }}>BirdDog</div>
        </div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, letterSpacing: '0.3em', color: '#fbbf24', textTransform: 'uppercase' }}>For Campus Patrol & Parking Authorities</div>
      </div>

      <div style={{ position: 'relative', zIndex: 1, maxWidth: 640 }}>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 11, letterSpacing: '0.3em', color: '#fbbf24', textTransform: 'uppercase', marginBottom: 18 }}>License Plate Recognition · iOS Patrol Suite</div>
        <div style={{ fontFamily: 'var(--bd-display)', fontSize: 64, fontWeight: 800, color: '#fafaf6', letterSpacing: '-0.04em', lineHeight: 0.95, marginBottom: 20 }}>
          Enforce parking policy<br/>at the speed of patrol.
        </div>
        <div style={{ fontFamily: 'var(--bd-body)', fontSize: 17, color: '#fafaf6', opacity: 0.75, lineHeight: 1.5, maxWidth: 540 }}>
          BirdDog turns any iPhone or iPad into a campus-grade ALPR scanner. Officers point, scan, and instantly see permit status, violation history, and citation tools — built for university security teams, not retrofitted from municipal software.
        </div>
      </div>
    </div>

    {/* Stats strip */}
    <div style={{ background: '#f3f1ea', padding: '24px 56px', display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #c8c3b1' }}>
      {[
        { k: 'Sub-second', v: 'Plate recognition' },
        { k: 'iOS 17+', v: 'iPhone & iPad native' },
        { k: 'Offline', v: 'Cached permit data' },
        { k: 'FERPA', v: 'Compliant by design' },
      ].map((s) => (
        <div key={s.k} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 24, fontWeight: 800, color: '#0a1428', letterSpacing: '-0.02em' }}>{s.k}</div>
          <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.28em', color: '#5a6373', textTransform: 'uppercase' }}>{s.v}</div>
        </div>
      ))}
    </div>

    {/* Features */}
    <div style={{ padding: '56px', display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 32 }}>
      {[
        {
          n: '01',
          t: 'Point-and-scan ALPR',
          d: 'Officers raise the device, the plate reads in real time. No buttons, no manual entry — works at walking speed across crowded lots.',
        },
        {
          n: '02',
          t: 'Permit & violation lookup',
          d: 'Instant sync with your existing permit database. Faculty, student, visitor, and event tiers — including time-windowed and zone-restricted parking.',
        },
        {
          n: '03',
          t: 'On-device citations',
          d: 'Issue tickets, warnings, or tow flags from the field. Photo evidence, voice memos, and signed officer audit trail attached automatically.',
        },
        {
          n: '04',
          t: 'Offline-first',
          d: 'Garage dead zones don\'t stop patrol. Cached permit data keeps scanning live; actions queue and sync when connectivity returns.',
        },
        {
          n: '05',
          t: 'Dispatch integration',
          d: 'Live patrol map for desk officers. Assign zones, monitor coverage, and pull shift reports in one click — no third-party CAD required.',
        },
        {
          n: '06',
          t: 'Built for higher ed',
          d: 'FERPA-aware logging, SSO via Shibboleth or Azure AD, and white-labeled deployments. Your seal, your colors, your policy.',
        },
      ].map((f) => (
        <div key={f.n} style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingTop: 14, borderTop: '1px solid #c8c3b1' }}>
          <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, letterSpacing: '0.3em', color: '#ca8a04' }}>{f.n}</div>
          <div style={{ fontFamily: 'var(--bd-display)', fontSize: 22, fontWeight: 700, letterSpacing: '-0.02em', color: '#0a1428' }}>{f.t}</div>
          <div style={{ fontFamily: 'var(--bd-body)', fontSize: 13, color: '#2d3340', lineHeight: 1.55 }}>{f.d}</div>
        </div>
      ))}
    </div>

    {/* Footer / CTA */}
    <div style={{ background: '#0a1428', padding: '48px 56px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'relative' }}>
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: 4, background: '#fbbf24' }} />
      <div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 10, letterSpacing: '0.3em', color: '#fbbf24', textTransform: 'uppercase', marginBottom: 10 }}>Now in beta · Moravian University</div>
        <div style={{ fontFamily: 'var(--bd-display)', fontSize: 32, fontWeight: 700, color: '#fafaf6', letterSpacing: '-0.02em', lineHeight: 1.1, maxWidth: 520 }}>
          Schedule a demo with your IT and parking authority.
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
        <div style={{ background: '#fbbf24', color: '#0a1428', padding: '14px 28px', borderRadius: 4, fontFamily: 'var(--bd-display)', fontSize: 15, fontWeight: 700, letterSpacing: '-0.01em' }}>
          birddog.app/demo →
        </div>
        <div style={{ fontFamily: 'var(--bd-mono)', fontSize: 9, letterSpacing: '0.28em', color: '#fafaf6', opacity: 0.5, textTransform: 'uppercase', marginTop: 4 }}>
          contact@birddog.app · © 2026
        </div>
      </div>
    </div>
  </div>
);

Object.assign(window, { SpecSheet, OnePager });
