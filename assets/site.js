/* T&A Abriss & Rückbau – gemeinsames Skript für alle Seiten (mit defer geladen).
   Jede Funktion läuft nur, wenn ihre Elemente auf der Seite vorhanden sind. */
(function(){
  'use strict';
  var $ = function(sel, root){ return (root || document).querySelector(sel); };
  var $$ = function(sel, root){ return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* Nächster möglicher Besichtigungstermin: #slot, alle [data-slot] und #wunsch */
  (function(){
    var slot = document.getElementById('slot'), extra = $$('[data-slot]'), wunsch = document.getElementById('wunsch');
    if (!slot && !extra.length && !wunsch) return;
    var days = ['Sonntag','Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag'];
    var t = new Date(Date.now() + 60 * 60000), s = null;
    for (var i = 0; i < 14 && !s; i++){
      var d = new Date(t.getFullYear(), t.getMonth(), t.getDate() + i), wd = d.getDay(), o = null, c = null;
      if (wd >= 1 && wd <= 5){ o = [16,30]; c = [19,0]; } else if (wd === 6){ o = [9,0]; c = [15,0]; }
      if (!o) continue;
      var a = new Date(d); a.setHours(o[0], o[1], 0, 0); var b = new Date(d); b.setHours(c[0], c[1], 0, 0);
      if (i === 0 && t > a){ a = new Date(t); a.setMinutes(a.getMinutes() <= 30 ? 30 : 60, 0, 0); }
      if (a <= b) s = a;
    }
    if (!s) return;
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var diff = Math.round((new Date(s.getFullYear(), s.getMonth(), s.getDate()) - today) / 864e5);
    var label = (diff === 0 ? 'Heute' : diff === 1 ? 'Morgen' : days[s.getDay()]) + ', ' + s.getHours() + ':' + String(s.getMinutes()).padStart(2, '0') + ' Uhr';
    if (slot) slot.textContent = label;
    extra.forEach(function(el){ el.textContent = label; });
    if (wunsch) wunsch.value = label;
  })();

  /* Anfrageformular: öffnet das E-Mail-Programm mit vorbereiteter Nachricht */
  (function(){
    var f = document.getElementById('f'), err = document.getElementById('err'), ok = document.getElementById('ok');
    if (!f) return;
    function el(id){ return document.getElementById(id); }
    function v(id){ var e = el(id); return e ? (e.value || '').trim() : ''; }
    function valid(){
      var bad = null;
      ['name','tel'].forEach(function(id){
        var e = el(id); if (!e) return;
        var empty = !e.value.trim();
        e.setAttribute('aria-invalid', empty ? 'true' : 'false');
        if (empty && !bad) bad = e;
      });
      if (err) err.hidden = !bad;
      if (bad) bad.focus();
      return !bad;
    }
    function msg(){
      var page = (f.getAttribute('data-page') || '').trim();
      return 'Hallo T&A Abriss & Rückbau, ich möchte eine Besichtigung anfragen.\n\nName: ' + v('name') +
        '\nTelefon: ' + v('tel') + '\nOrt: ' + (v('ort') || '-') + '\nLeistung: ' + v('art') +
        '\nWunschtermin: ' + (v('wunsch') || '-') + (page ? '\nSeite: ' + page : '') +
        (v('text') ? '\n\n' + v('text') : '');
    }
    f.addEventListener('submit', function(e){
      e.preventDefault();
      if (!valid()) return;
      if (ok) ok.hidden = false;
      location.href = 'mailto:info@ta-abriss-hamburg.de?subject=' + encodeURIComponent('Anfrage Besichtigung') + '&body=' + encodeURIComponent(msg());
    });
  })();

  /* Schnellkontakt (.fab: Handy = Leiste „Anrufen“ + „Anfrage“, PC = Anfrage-Knopf):
     sichtbar nach dem Hero, aus am Kontaktbereich */
  (function(){
    var fab = $('.fab'), hero = $('.hero, .subhero'), contact = document.getElementById('anfrage'), tick = false;
    if (!fab || !hero) return;
    function sync(){
      var past = hero.getBoundingClientRect().bottom < 0;
      var atForm = contact ? contact.getBoundingClientRect().top < innerHeight * 0.6 : false;
      fab.classList.toggle('on', past && !atForm);
    }
    addEventListener('scroll', function(){ if (!tick){ tick = true; requestAnimationFrame(function(){ sync(); tick = false; }); } }, {passive: true});
    addEventListener('resize', sync);
    sync();
  })();

  /* Menü mit drei Strichen */
  (function(){
    var btn = $('.burger[aria-controls="menu"]'), menu = document.getElementById('menu'), header = $('header.top');
    if (!btn || !menu) return;
    var root = document.documentElement, scrim = null, isOpen = false;

    function place(){
      var hb = header ? header.getBoundingClientRect().bottom : btn.getBoundingClientRect().bottom + 12;
      root.style.setProperty('--menu-top', Math.max(0, Math.round(hb)) + 'px');
      var right = Math.max(16, Math.round(innerWidth - btn.getBoundingClientRect().right));
      root.style.setProperty('--menu-right', right + 'px');
    }
    function links(){ return $$('a[href], button:not([disabled])', menu).filter(function(a){ return a.offsetParent !== null || a.getClientRects().length; }); }
    function open(){
      if (isOpen) return;
      isOpen = true;
      place();
      menu.classList.add('open');
      root.classList.add('menu-open');
      btn.setAttribute('aria-expanded', 'true');
      btn.setAttribute('aria-label', 'Menü schließen');
      if (!scrim){ scrim = document.createElement('div'); scrim.className = 'scrim'; scrim.setAttribute('aria-hidden', 'true'); }
      document.body.appendChild(scrim);
      menu.scrollTop = 0;
      var first = links()[0];
      if (first) first.focus({preventScroll: true});
    }
    function close(refocus){
      if (!isOpen) return;
      isOpen = false;
      menu.classList.remove('open');
      root.classList.remove('menu-open');
      btn.setAttribute('aria-expanded', 'false');
      btn.setAttribute('aria-label', 'Menü öffnen');
      if (scrim && scrim.parentNode) scrim.parentNode.removeChild(scrim);
      if (refocus) btn.focus({preventScroll: true});
    }

    btn.addEventListener('click', function(){ isOpen ? close(true) : open(); });
    menu.addEventListener('click', function(e){
      var a = e.target.closest ? e.target.closest('a[href]') : null;
      if (a) close(false);
    });
    document.addEventListener('click', function(e){
      if (!isOpen || menu.contains(e.target) || btn.contains(e.target)) return;
      var ae = document.activeElement;
      close(!ae || ae === document.body || menu.contains(ae));
    });
    document.addEventListener('keydown', function(e){
      if (!isOpen) return;
      if (e.key === 'Escape' || e.key === 'Esc'){ e.preventDefault(); close(true); return; }
      if (e.key !== 'Tab') return;
      /* Fokus bleibt zwischen Knopf und Menü, solange es offen ist */
      var items = links(); if (!items.length) return;
      var first = items[0], last = items[items.length - 1], ae = document.activeElement;
      if (!e.shiftKey && ae === last){ e.preventDefault(); btn.focus(); }
      else if (!e.shiftKey && ae === btn){ e.preventDefault(); first.focus(); }
      else if (e.shiftKey && ae === first){ e.preventDefault(); btn.focus(); }
      else if (e.shiftKey && ae === btn){ e.preventDefault(); last.focus(); }
      else if (!menu.contains(ae) && ae !== btn){ e.preventDefault(); first.focus(); }
    });
    addEventListener('resize', function(){ if (isOpen) place(); });
  })();
})();
