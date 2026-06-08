// Connects to api.telegram.org and dumps the certificate chain, ignoring
// validation errors. Reveals whether something is intercepting TLS.
//
// Run:  node diagnose-tls.js

const tls = require('tls');

const socket = tls.connect(
  443,
  'api.telegram.org',
  { servername: 'api.telegram.org', rejectUnauthorized: false },
  () => {
    console.log('Connected. authorized =', socket.authorized);
    if (!socket.authorized) console.log('reason     =', socket.authorizationError);
    console.log('protocol   =', socket.getProtocol());
    console.log();

    let cert = socket.getPeerCertificate(true);
    let depth = 0;
    const seen = new Set();
    while (cert && !seen.has(cert.fingerprint256)) {
      seen.add(cert.fingerprint256);
      console.log(`--- depth ${depth} ---`);
      console.log('subject:', formatName(cert.subject));
      console.log('issuer :', formatName(cert.issuer));
      console.log('valid  :', cert.valid_from, '->', cert.valid_to);
      console.log('fp     :', cert.fingerprint256);
      console.log();
      if (cert.issuerCertificate && cert.issuerCertificate !== cert) {
        cert = cert.issuerCertificate;
        depth++;
      } else break;
    }
    socket.end();
  }
);

socket.on('error', (e) => {
  console.error('socket error:', e.message);
});

function formatName(n) {
  if (!n) return '(none)';
  return Object.entries(n).map(([k, v]) => `${k}=${v}`).join(', ');
}
