'use strict';
// Execute the shipped inline script, not a reimplementation of its state machine.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const html = fs.readFileSync(path.join(__dirname, '../../assets/dashboard/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const flush = () => new Promise(resolve => setImmediate(resolve));

function browser() {
  const elements = new Map(), pending = [], confirmations = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', disabled: false, hidden: true, textContent: '', innerHTML: '',
      classList: {toggle() {}}, listeners: {},
      addEventListener(event, fn) { this.listeners[event] = fn; },
    });
    return elements.get(id);
  }
  const response = (data, status=200) => ({ok: status < 400, status, json: async () => data});
  const context = vm.createContext({
    document: {getElementById: element, querySelectorAll: () => []},
    window: {addEventListener() {}, location: {origin: 'http://127.0.0.1:8765'}},
    location: {origin: 'http://127.0.0.1:8765'},
    confirm: message => {confirmations.push(message); return true;},
    setInterval() {}, console,
    fetch(url, options={}) {
      if (url === '/api/session') return Promise.resolve(response({token: 'session-secret'}));
      if (url === '/api/status') return Promise.resolve(response({book_name: 'test', total_chars: 0, last_chapter: 0, chapter_count: 0, daily_avg: 0}));
      if (url === '/api/chapters') return Promise.resolve(response([]));
      if (url === '/api/file-tree') return Promise.resolve(response({dirs: []}));
      return new Promise((resolve, reject) => pending.push({url, options,
        reply: (data, status) => resolve(response(data, status)), reject}));
    },
  });
  vm.runInContext(script, context, {filename: 'assets/dashboard/index.html'});
  return {
    context, element, pending, confirmations,
    state: () => vm.runInContext('openFile', context),
    async request(fn, ...args) {
      const done = context[fn](...args);
      await flush();
      const request = pending.shift();
      assert.ok(request, `${fn} must send a request`);
      return {done, ...request};
    },
    edit(value) {element('file-editor').value=value; element('file-editor').listeners.input();},
    async open(name) {
      const request = await this.request('previewFile', name);
      request.reply({path: name, revision: name+'-r1', content: name+' original', extension: '.md'});
      await request.done;
    },
  };
}

test('normal load, dirty edit, authenticated save and recoverable delete', async () => {
  const b=browser(); await b.open('A.md'); b.edit('saved');
  const save=await b.request('saveOpenFile');
  assert.equal(save.options.headers['X-Dashboard-Token'], 'session-secret');
  assert.deepEqual(JSON.parse(save.options.body), {path:'A.md', content:'saved', revision:'A.md-r1'});
  save.reply({revision:'r2', extension:'.md', backup:'backup'}); await save.done;
  assert.equal(b.state().dirty, false); assert.equal(b.state().revision, 'r2');
  const del=await b.request('deleteOpenFile');
  assert.equal(del.options.headers['X-Dashboard-Token'], 'session-secret');
  del.reply({trash_path:'trash/A.md'}); await del.done;
  assert.equal(b.state().path, ''); assert.equal(b.element('file-editor').value, '');
});

test('pending preview cannot silently discard input typed after navigation started', async () => {
  const b=browser(); await b.open('A.md');
  const next=await b.request('previewFile','B.md'); b.edit('new A input');
  next.reply({path:'B.md', revision:'b1', content:'B original', extension:'.md'}); await next.done;
  assert.equal(b.state().path,'A.md'); assert.equal(b.element('file-editor').value,'new A input');
  assert.equal(b.state().dirty,true);
});

test('out of order preview responses and old errors cannot replace the newest file', async () => {
  const b=browser(); await b.open('A.md');
  const first=await b.request('previewFile','B.md');
  await b.open('C.md'); first.reply({path:'B.md', revision:'b1', content:'B', extension:'.md'}); await first.done;
  assert.equal(b.state().path,'C.md');
  const stale=await b.request('previewFile','B.md'); await b.open('D.md');
  stale.reject(new Error('old error')); await stale.done;
  assert.equal(b.state().path,'D.md'); assert.equal(b.element('editor-message').hidden,true);
});

test('save response for A never changes B identity revision or buffer', async () => {
  const b=browser(); await b.open('A.md'); b.edit('A changed');
  const save=await b.request('saveOpenFile'); await b.open('B.md'); b.edit('B changed');
  save.reply({revision:'A-r2', extension:'.md'}); await save.done;
  assert.equal(b.state().path,'B.md'); assert.equal(b.state().revision,'B.md-r1');
  assert.equal(b.state().content,'B.md original'); assert.equal(b.element('file-editor').value,'B changed');
});

test('save same file preserves newer typing while updating saved base revision', async () => {
  const b=browser(); await b.open('A.md'); b.edit('sent');
  const save=await b.request('saveOpenFile'); b.edit('newer');
  save.reply({revision:'r2', extension:'.md'}); await save.done;
  assert.equal(b.element('file-editor').value,'newer'); assert.equal(b.state().content,'sent');
  assert.equal(b.state().revision,'r2'); assert.equal(b.state().dirty,true);
});

test('delete response for A cannot clear B and failure cannot restore stale A buffer', async () => {
  for (const fail of [false,true]) {
    const b=browser(); await b.open('A.md');
    const del=await b.request('deleteOpenFile'); await b.open('B.md'); b.edit('B typing');
    if(fail) del.reject(new Error('network')); else del.reply({trash_path:'trash/A'});
    await del.done;
    assert.equal(b.state().path,'B.md'); assert.equal(b.element('file-editor').value,'B typing');
    assert.equal(b.state().revision,'B.md-r1');
  }
});

test('delete success preserves input typed while request was pending', async () => {
  const b=browser(); await b.open('A.md');
  const del=await b.request('deleteOpenFile'); b.edit('must survive');
  del.reply({trash_path:'trash/A'}); await del.done;
  assert.equal(b.element('file-editor').value,'must survive'); assert.equal(b.state().dirty,true);
  assert.equal(b.state().path,'A.md');
});

test('409 and network failures preserve the current edited buffer', async () => {
  for(const fn of ['saveOpenFile','deleteOpenFile']) {
    for(const fail of [false,true]) {
      const b=browser(); await b.open('A.md'); b.edit('sent');
      const request=await b.request(fn); b.edit('newer');
      if(fail) request.reject(new Error('network')); else request.reply({error:'conflict'},409);
      await request.done;
      assert.equal(b.element('file-editor').value,'newer'); assert.equal(b.state().revision,'A.md-r1');
      assert.equal(b.state().dirty,true);
      if(!fail) assert.equal(b.element('conflict-banner').hidden,false);
    }
  }
});

test('in-flight mutations are serialized, including across file switches', async () => {
  const b=browser(); await b.open('A.md'); b.edit('sent');
  const first=await b.request('saveOpenFile');
  b.context.saveOpenFile(); b.context.deleteOpenFile();
  await flush();
  assert.equal(b.pending.length,0);
  await b.open('B.md'); b.context.saveOpenFile(); await flush();
  assert.equal(b.pending.length,0);
  first.reply({revision:'r2',extension:'.md'}); await first.done;
});
