//! Trust-store regression checks for the update check's HTTPS client (ureq -> rustls -> webpki-roots).
//!
//! Background: in October 2026 eight eMudhra (emSign) intermediate keys were disclosed. webpki-roots 1.0.10 removed
//! the root that signed them, `emSign ECC Root CA - G3` (RUSTSEC-2026-0381). The 0.26.11 release that ureq 2 depends
//! on is a wrapper that re-exports the roots of a separately resolved 1.x crate, so the lockfile must resolve that
//! 1.x crate to 1.0.10 or newer. These tests read the roots the binary actually embeds, not the manifest.
//!
//! Sources: https://rustsec.org/advisories/RUSTSEC-2026-0381.html and
//! https://github.com/rustls/webpki-roots/pull/133 (SPKI SHA-256 of the removed root).
use std::sync::Arc;

use rustls::client::danger::ServerCertVerifier;
use rustls::client::WebPkiServerVerifier;
use rustls::pki_types::{CertificateDer, ServerName, UnixTime};
use rustls::RootCertStore;
use sha2::{Digest, Sha256};

/// SPKI SHA-256 of `emSign ECC Root CA - G3`, as published in rustls/webpki-roots PR 133.
const REMOVED_ROOT_SPKI_SHA256: &str = "8d417db2dd8bf5e3084d1e3f196d583849d81bdd4c00c70b9d39369e96b8c782";

const TEST_CA: &[u8] = include_bytes!("fixtures/trust/test-ca.der");
const TEST_LEAF: &[u8] = include_bytes!("fixtures/trust/test-leaf.der");
const TEST_NAME: &str = "studio-test.example";

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// SHA-256 of the full DER `SubjectPublicKeyInfo`. webpki-roots stores only the contents of that SEQUENCE, so the
/// tag and length are put back before hashing; this is the form SPKI pins (and the PR's identifier) are computed over.
fn spki_sha256(contents: &[u8]) -> String {
    let mut der = vec![0x30];
    match contents.len() {
        n if n < 0x80 => der.push(n as u8),
        n if n < 0x100 => der.extend([0x81, n as u8]),
        n => der.extend([0x82, (n >> 8) as u8, n as u8]),
    }
    der.extend_from_slice(contents);
    hex(&Sha256::digest(&der))
}

fn embedded_spki_hashes() -> Vec<String> {
    webpki_roots::TLS_SERVER_ROOTS.iter().map(|ta| spki_sha256(ta.subject_public_key_info.as_ref())).collect()
}

fn verifier(extra_roots: &[&[u8]]) -> Arc<WebPkiServerVerifier> {
    let mut roots = RootCertStore::empty();
    roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    for der in extra_roots {
        roots.add(CertificateDer::from(der.to_vec())).expect("fixture CA is a valid certificate");
    }
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    WebPkiServerVerifier::builder_with_provider(Arc::new(roots), provider)
        .build()
        .expect("verifier builds from the embedded roots")
}

fn verify(v: &Arc<WebPkiServerVerifier>, name: &str) -> Result<(), rustls::Error> {
    let leaf = CertificateDer::from(TEST_LEAF.to_vec());
    let server = ServerName::try_from(name.to_owned()).expect("valid DNS name");
    v.verify_server_cert(&leaf, &[], &server, &[], UnixTime::now()).map(|_| ())
}

#[test]
fn embedded_roots_exclude_the_removed_emsign_ecc_g3_anchor() {
    let hashes = embedded_spki_hashes();
    assert!(hashes.len() > 100, "the embedded store is unexpectedly small: {}", hashes.len());
    assert!(
        !hashes.iter().any(|h| h == REMOVED_ROOT_SPKI_SHA256),
        "the embedded trust store still contains emSign ECC Root CA - G3 (RUSTSEC-2026-0381); \
         webpki-roots 1.x must resolve to 1.0.10 or newer"
    );
}

#[test]
fn no_embedded_anchor_is_named_emsign_ecc_g3() {
    // Belt and braces for the SPKI check: a re-issued key for the same subject would still be the same CA.
    let needle = b"emSign ECC Root CA - G3";
    let found = webpki_roots::TLS_SERVER_ROOTS
        .iter()
        .any(|ta| ta.subject.as_ref().windows(needle.len()).any(|w| w == needle));
    assert!(!found, "an embedded anchor is still named emSign ECC Root CA - G3");
}

#[test]
fn remaining_emsign_anchors_are_listed_for_review() {
    // Not an assertion about trust: RUSTSEC-2026-0381 and the PR remove only the G3 ECC root, and the sources do
    // not say another emSign root is compromised. This prints what remains so a reviewer can see it (--nocapture).
    let needle = b"emSign";
    for ta in webpki_roots::TLS_SERVER_ROOTS.iter() {
        if ta.subject.as_ref().windows(needle.len()).any(|w| w == needle) {
            println!("remaining emSign anchor, SPKI sha256 {}", spki_sha256(ta.subject_public_key_info.as_ref()));
        }
    }
}

#[test]
fn lockfile_resolves_the_webpki_roots_1x_crate_to_1_0_10_or_newer() {
    let lock = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.lock")).expect("Cargo.lock");
    let mut versions = Vec::new();
    let mut lines = lock.lines();
    while let Some(line) = lines.next() {
        if line == "name = \"webpki-roots\"" {
            let version = lines.next().and_then(|l| l.strip_prefix("version = \"")).and_then(|l| l.strip_suffix('"')).expect("version line");
            versions.push(version.to_owned());
        }
    }
    assert!(!versions.is_empty(), "webpki-roots is not in the lockfile");
    for v in &versions {
        let parts: Vec<u64> = v.split(['-', '+']).next().unwrap().split('.').map(|p| p.parse().expect("numeric version")).collect();
        match parts[0] {
            0 => assert_eq!(v, "0.26.11", "only the 0.26.11 wrapper is acceptable on the 0.x line"),
            1 => assert!(parts[1] > 0 || parts[2] >= 10, "webpki-roots {v} still trusts the removed emSign root"),
            _ => {}
        }
    }
    assert!(versions.iter().any(|v| v.starts_with("1.")), "the wrapper's 1.x dependency must be locked explicitly: {versions:?}");
}

#[test]
fn a_valid_chain_for_the_right_name_verifies() {
    // Public-root validation still works: a chain to a CA we add is accepted for its own name.
    assert!(verify(&verifier(&[TEST_CA]), TEST_NAME).is_ok());
}

#[test]
fn the_wrong_hostname_is_rejected() {
    let err = verify(&verifier(&[TEST_CA]), "other.example").expect_err("hostname validation must stay on");
    let text = format!("{err:?}");
    assert!(text.contains("NotValidForName") || text.contains("NotValidForNameContext"), "unexpected error: {text}");
}

#[test]
fn a_chain_to_an_unknown_issuer_is_rejected() {
    // The test CA is not among the embedded roots, so without adding it the same leaf must not verify.
    let err = verify(&verifier(&[]), TEST_NAME).expect_err("an unknown issuer must be refused");
    let text = format!("{err:?}");
    assert!(text.contains("UnknownIssuer"), "unexpected error: {text}");
}

#[test]
fn lockfile_resolves_rustls_webpki_to_a_release_that_rejects_the_distrusted_emsign_intermediates() {
    // RUSTSEC-2026-0382: the verifier itself refuses paths through the disclosed emSign intermediate keys from
    // 0.103.16. This is the second half of the fix; the embedded roots alone do not cover alternate paths.
    let lock = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.lock")).expect("Cargo.lock");
    let mut lines = lock.lines();
    let mut found = Vec::new();
    while let Some(line) = lines.next() {
        if line == "name = \"rustls-webpki\"" {
            found.push(lines.next().and_then(|l| l.strip_prefix("version = \"")).and_then(|l| l.strip_suffix('"')).expect("version").to_owned());
        }
    }
    assert!(!found.is_empty(), "rustls-webpki is not in the lockfile");
    for v in &found {
        let p: Vec<u64> = v.split(|c: char| c == '.' || c == '-').take(3).map(|x| x.parse().unwrap_or(0)).collect();
        let ok = (p[0], p[1]) == (0, 103) && p[2] >= 16 || (p[0], p[1]) > (0, 103);
        assert!(ok, "rustls-webpki {v} still accepts distrusted emSign intermediates (needs >= 0.103.16)");
    }
}
