(() => {
  function addInteractiveClass(root = document) {
    root.querySelectorAll('button, a, [role="button"], select, input[type="button"], input[type="submit"]').forEach(el => {
      el.classList.add('cm-interactive');
      if (el.matches('button, a, [role="button"]')) el.classList.add('cm-ripple-host');
      if (el.id === 'account-menu' || el.id === 'account-menu-button' || el.id === 'account-menu-dropdown') el.classList.add('cm-menu');
    });
  }

  function addRipple(el, event) {
    if (!el || el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return;
    if (el.dataset.noRipple === 'true') return;

    const rect = el.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;

    const ripple = document.createElement('span');
    ripple.className = 'cm-ripple';
    ripple.style.left = x + 'px';
    ripple.style.top = y + 'px';
    el.appendChild(ripple);
    window.setTimeout(() => ripple.remove(), 520);

    el.classList.remove('cm-click-pop');
    void el.offsetWidth;
    el.classList.add('cm-click-pop');
    window.setTimeout(() => el.classList.remove('cm-click-pop'), 180);
  }

  function observeMessages() {
    const selectors = ['#mentor-messages', '#mentor-chat', '[data-message-list]'];
    selectors.forEach(selector => {
      document.querySelectorAll(selector).forEach(host => {
        const observer = new MutationObserver(mutations => {
          mutations.forEach(mutation => {
            mutation.addedNodes.forEach(node => {
              if (!(node instanceof HTMLElement)) return;
              node.classList.add('cm-message-enter');
            });
          });
        });
        observer.observe(host, { childList: true });
      });
    });
  }

  document.addEventListener('pointerdown', event => {
    const target = event.target.closest('button, a, [role="button"], select, input[type="button"], input[type="submit"]');
    if (target) addRipple(target, event);
  }, { passive: true });

  function wireNavigationTransitions() {
    document.addEventListener('click', event => {
      const anchor = event.target.closest('a[href]');
      if (!anchor) return;
      if (anchor.target === '_blank' || anchor.hasAttribute('download')) return;
      const href = anchor.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;
      let url;
      try { url = new URL(href, window.location.href); } catch (_) { return; }
      if (url.origin !== window.location.origin) return;
      if (url.href === window.location.href) return;
      event.preventDefault();
      document.body.classList.add('cm-page-leaving');
      window.setTimeout(() => { window.location.href = url.href; }, 150);
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.body.classList.add('cm-page-enter');
    wireNavigationTransitions();
    addInteractiveClass();
    observeMessages();

    const observer = new MutationObserver(mutations => {
      mutations.forEach(mutation => {
        mutation.addedNodes.forEach(node => {
          if (node instanceof HTMLElement) addInteractiveClass(node);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });

    document.querySelectorAll('#mentor-open, #mentor-trigger, [data-mentor-open]').forEach(button => {
      button.addEventListener('click', () => {
        button.classList.remove('cm-click-pop');
        void button.offsetWidth;
        button.classList.add('cm-click-pop');
      });
    });
  });
})();