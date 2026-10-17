const _fs = require('fs');
const _vm = require('vm');
const _crypto = require('crypto');
const path = require('path');

const wasmPath = path.join(__dirname, 'ecdh.wasm');
const jsPath = path.join(__dirname, 'ecdh.js');

global.window = global;
global.require = require;
global.__dirname = __dirname;

global.Module = {
  instantiateWasm: function(info, receiveInstance) {
    const bytes = _fs.readFileSync(wasmPath);
    const wasmModule = new WebAssembly.Module(bytes);
    const instance = new WebAssembly.Instance(wasmModule, info);
    receiveInstance(instance, wasmModule);
    return instance.exports;
  }
};

_vm.runInThisContext(_fs.readFileSync(jsPath, 'utf8'));

const PUB_SIZE = 48;
const PRV_SIZE = 24;

const cmd = process.argv[2];

if (cmd === 'generate') {
  const prvBuf = Module._malloc(PRV_SIZE);
  const pubBuf = Module._malloc(PUB_SIZE);
  const prv = Module.HEAPU8.subarray(prvBuf, prvBuf + PRV_SIZE);
  const pub = Module.HEAPU8.subarray(pubBuf, pubBuf + PUB_SIZE);
  
  _crypto.randomFillSync(prv);
  Module._ecdh_generate_keys(pubBuf, prvBuf);
  
  const prvHex = Buffer.from(prv).toString('hex');
  const pubHex = Buffer.from(pub).toString('hex');
  
  console.log(JSON.stringify({ privateKey: prvHex, publicKey: pubHex }));
} else if (cmd === 'secret') {
  const prvHex = process.argv[3];
  const pubHex = process.argv[4];
  
  const prvBuf = Module._malloc(PRV_SIZE);
  const pubBuf = Module._malloc(PUB_SIZE);
  const secBuf = Module._malloc(PUB_SIZE);
  
  const prv = Module.HEAPU8.subarray(prvBuf, prvBuf + PRV_SIZE);
  const pub = Module.HEAPU8.subarray(pubBuf, pubBuf + PUB_SIZE);
  
  prv.set(Buffer.from(prvHex, 'hex'));
  pub.set(Buffer.from(pubHex, 'hex'));
  
  Module._ecdh_shared_secret(prvBuf, pubBuf, secBuf);
  const sec = Buffer.from(Module.HEAPU8.subarray(secBuf, secBuf + PUB_SIZE));
  
  console.log(JSON.stringify({ sharedSecret: sec.toString('hex') }));
} else {
  console.error('Unknown command. Use generate or secret <prvHex> <pubHex>');
  process.exit(1);
}
