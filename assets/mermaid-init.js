(function () {
  // The fence renders as class="mermaid-src" (not "mermaid") specifically
  // so mermaid.js's own default auto-init -- which fires the moment its
  // script loads, before this script gets a chance to run -- never touches
  // these elements. We convert them to real .mermaid elements ourselves,
  // once, with plain unwrapped text (pymdownx.superfences nests a <code>
  // inside <pre>, which mermaid.run()'s own extraction can't handle).
  mermaid.initialize({
    startOnLoad: false,
    theme: 'base',
    themeVariables: {
      primaryColor: '#f9f4ed',
      primaryBorderColor: '#645c50',
      primaryTextColor: '#201e1d',
      lineColor: '#645c50'
    }
  });

  function render() {
    document.querySelectorAll('pre.mermaid-src').forEach(function (pre) {
      var code = pre.querySelector('code');
      var text = code ? code.textContent : pre.textContent;
      var el = document.createElement('pre');
      el.className = 'mermaid';
      el.textContent = text;
      pre.replaceWith(el);
    });
    // Idempotent: skip elements a previous call (ours or the theme's own
    // reactive document$ subscription firing independently) already turned
    // into rendered SVG -- re-running on those feeds SVG markup back into
    // the parser as if it were graph syntax, which fails as a "Syntax error".
    mermaid.run({ querySelector: '.mermaid:not([data-processed])' });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', render);
  } else {
    render();
  }
})();
