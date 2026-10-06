(() => {
  const THEME_KEY = 'codementor-theme';
  const ICON_LABELS = {
    arrow_back: 'Go back',
    arrow_forward: 'Go forward',
    close: 'Close',
    delete: 'Delete',
    edit: 'Edit',
    help: 'Help',
    info: 'Information',
    logout: 'Log out',
    menu: 'Open menu',
    more_horiz: 'More options',
    person: 'Account',
    refresh: 'Refresh',
    save: 'Save',
    search: 'Search',
    settings: 'Settings',
    terminal: 'CodeMentor AI',
  };

  function getThemePreference() {
    const saved = localStorage.getItem(THEME_KEY);
    return saved === 'light' || saved === 'dark' ? saved : 'light';
  }

  function applyTheme(theme) {
    const normalized = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.cmTheme = normalized;

    // Preserve the existing Tailwind dark-mode contract for pages that opt in.
    document.documentElement.classList.toggle('dark', normalized === 'dark');

    window.dispatchEvent(new CustomEvent('codementor:themechange', {
      detail: { theme: normalized }
    }));

    return normalized;
  }

  function setTheme(theme) {
    const normalized = applyTheme(theme);
    localStorage.setItem(THEME_KEY, normalized);
    return normalized;
  }

  function toggleTheme() {
    return setTheme(
      document.documentElement.dataset.cmTheme === 'dark' ? 'light' : 'dark'
    );
  }

  function syncThemeFromStorage() {
    return applyTheme(getThemePreference());
  }

  function isInteractiveControl(el) {
    return el.matches(
      'button, a, [role="button"], select, input[type="button"], ' +
      'input[type="submit"], input[type="reset"]'
    );
  }

  function isEditorControl(el) {
    return Boolean(
      el.closest(
        '.monaco-editor, [data-code-editor], [data-editor], .cm-editor'
      )
    );
  }

  function addInteractiveClass(root = document) {
    root.querySelectorAll(
      'button, a, [role="button"], select, input[type="button"], ' +
      'input[type="submit"], input[type="reset"]'
    ).forEach(el => {
      el.classList.add('cm-interactive');

      if (!isEditorControl(el) && el.matches('button, a, [role="button"]')) {
        el.classList.add('cm-ripple-host');
      }

      if (
        el.id === 'account-menu' ||
        el.id === 'account-menu-button' ||
        el.id === 'account-menu-dropdown'
      ) {
        el.classList.add('cm-menu');
      }
    });
  }

  function enhanceButtons(root = document) {
    root.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"], input[type="reset"]')
      .forEach(button => {
        if (isEditorControl(button)) return;

        button.classList.add('cm-auto-button');

        const text = (button.innerText || button.value || '').replace(/\s+/g, ' ').trim();
        const hasLabel = text.length > 0;
        button.dataset.cmHasLabel = hasLabel ? 'true' : 'false';

        const label =
          button.getAttribute('aria-label') ||
          button.getAttribute('title') ||
          (button.querySelector('.material-symbols-outlined, .material-symbols-rounded, .material-icons')
            ?.textContent || '')
            .trim()
            .toLowerCase();

        const accessibleName = button.getAttribute('aria-label') || button.getAttribute('aria-labelledby');
        if (!accessibleName && !hasLabel && label) {
          button.setAttribute('aria-label', ICON_LABELS[label] || label.replace(/_/g, ' '));
        }

        if (!hasLabel && !button.getAttribute('aria-label') && !button.getAttribute('aria-labelledby')) {
          button.dataset.cmIconOnly = 'true';
        } else {
          button.dataset.cmIconOnly = 'false';
        }
      });
  }

  function enhanceForms(root = document) {
    root.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), select, textarea')
      .forEach(control => {
        if (isEditorControl(control)) return;
        control.classList.add('cm-auto-input');

        const name = control.getAttribute('name') || control.id;
        if (!control.getAttribute('aria-label') && !control.getAttribute('aria-labelledby') && name) {
          const label = document.querySelector('label[for="' + CSS.escape(control.id || '') + '"]');
          if (label && control.id) {
            control.setAttribute('aria-labelledby', label.id || ensureLabelId(label, control));
          }
        }
      });
  }

  let labelSequence = 0;
  function ensureLabelId(label, control) {
    if (!label.id) {
      labelSequence += 1;
      label.id = 'cm-label-' + labelSequence + '-' + (control.id || 'field');
    }
    return label.id;
  }

  function enhanceCards(root = document) {
    root.querySelectorAll('div, section, article, aside').forEach(el => {
      if (el.classList.contains('monaco-editor') || el.closest('.monaco-editor')) return;
      const classes = el.className;
      if (typeof classes !== 'string') return;

      const looksLikeCard =
        /\bbg-(?:white|surface-container-lowest|surface|background)\b/.test(classes) &&
        /\brounded-(?:lg|xl|2xl)\b/.test(classes) &&
        (/[\s:]shadow(?:-|\b)/.test(classes) || /\bborder\b/.test(classes));

      if (looksLikeCard) el.classList.add('cm-auto-card');
    });
  }

  function enhanceNavigation(root = document) {
    const current = new URL(window.location.href);
    const currentPath = current.pathname.split('/').pop() || 'index.html';

    root.querySelectorAll('header nav, nav').forEach(nav => {
      nav.classList.add('cm-auto-nav');

      nav.querySelectorAll('a[href]').forEach(anchor => {
        let target;
        try {
          target = new URL(anchor.getAttribute('href'), window.location.href);
        } catch (_) {
          return;
        }

        if (target.origin !== current.origin) return;

        const targetPath = target.pathname.split('/').pop() || 'index.html';
        if (targetPath === currentPath && !anchor.matches('[aria-current]')) {
          anchor.setAttribute('aria-current', 'page');
        }
      });
    });
  }

  function addSkipLink() {
    const main = document.querySelector('main');
    if (!main || document.querySelector('.cm-skip-link')) return;

    if (!main.id) main.id = 'main-content';

    const skip = document.createElement('a');
    skip.className = 'cm-skip-link';
    skip.href = '#' + main.id;
    skip.textContent = 'Skip to main content';
    document.body.prepend(skip);
  }

  function enhanceAlerts(root = document) {
    root.querySelectorAll('[role="alert"], #error, #message, #syntax-status').forEach(el => {
      if (el.matches('#syntax-status')) {
        el.classList.add('cm-auto-alert');
        return;
      }
      el.classList.add('cm-auto-alert');
    });
  }

  function enhance(root = document) {
    addInteractiveClass(root);
    enhanceButtons(root);
    enhanceForms(root);
    enhanceCards(root);
    enhanceNavigation(root);
    enhanceAlerts(root);
  }

  function addRipple(el, event) {
    if (!el || el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true') return;
    if (el.dataset.noRipple === 'true' || isEditorControl(el)) return;

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

  function wireNavigationTransitions() {
    document.addEventListener('click', event => {
      const anchor = event.target.closest('a[href]');
      if (!anchor) return;
      if (anchor.target === '_blank' || anchor.hasAttribute('download')) return;

      const href = anchor.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;

      let url;
      try {
        url = new URL(href, window.location.href);
      } catch (_) {
        return;
      }

      if (url.origin !== window.location.origin) return;
      if (url.href === window.location.href) return;

      event.preventDefault();
      document.body.classList.add('cm-page-leaving');
      window.setTimeout(() => {
        window.location.href = url.href;
      }, 150);
    });
  }

  document.addEventListener('pointerdown', event => {
    const target = event.target.closest(
      'button, a, [role="button"], select, input[type="button"], ' +
      'input[type="submit"], input[type="reset"]'
    );
    if (target) addRipple(target, event);
  }, { passive: true });

  document.addEventListener('DOMContentLoaded', () => {
    syncThemeFromStorage();

    document.body.classList.add('cm-page-enter');
    addSkipLink();
    enhance(document);
    wireNavigationTransitions();
    observeMessages();

    const observer = new MutationObserver(mutations => {
      const added = [];
      mutations.forEach(mutation => {
        mutation.addedNodes.forEach(node => {
          if (node instanceof HTMLElement) added.push(node);
        });
      });

      added.forEach(node => enhance(node));
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });

    document.querySelectorAll(
      '#mentor-open, #mentor-trigger, [data-mentor-open]'
    ).forEach(button => {
      button.addEventListener('click', () => {
        button.classList.remove('cm-click-pop');
        void button.offsetWidth;
        button.classList.add('cm-click-pop');
      });
    });

    // Public, page-agnostic API for a future shared theme control.
    window.CodeMentorUI = {
      getTheme: () => document.documentElement.dataset.cmTheme || 'light',
      setTheme,
      toggleTheme,
      enhance,
    };

    window.dispatchEvent(new CustomEvent('codementor:ready', {
      detail: { version: '1.0.0' }
    }));
  });
})();
