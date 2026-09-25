# Quarry / BirdDog — CJIS Security Policy v6.1 Compliance Checklist

**Purpose:** Map every CJIS requirement to what Quarry (backend) and BirdDog (iOS app) must implement before integrating with Pennsylvania JNET for license plate and registered owner lookups.

**Reference:** FBI CJIS Security Policy v6.1, effective June 25, 2026. Controls marked Priority 1 are sanctionable now. Priority 2–4 have a zero-cycle grace period through September 30, 2027.

---

## 1. Encryption

### In Transit (SC-8)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| TLS 1.2 or higher for all CJI transmission | Quarry backend API must enforce TLS 1.2+ with minimum 128-bit symmetric key strength. No fallback to older protocols. | ☐ |
| FIPS 140-3 validated cryptographic modules | Use FIPS-validated TLS libraries. On iOS, Apple's built-in TLS (Network.framework / URLSession) uses FIPS 140-2 validated modules — confirm 140-3 status or document equivalency. | ☐ |
| Wireless encryption (AC-18) | BirdDog communicating over Wi-Fi must use WPA2/WPA3. Cellular data is inherently encrypted but document this. | ☐ |

### At Rest (SC-28)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Encrypt CJI at rest using FIPS 140-3 validated modules | Any CJI cached on the iOS device (plate lookup results, registered owner info) must be stored in encrypted containers. iOS Data Protection (NSFileProtectionComplete) + Keychain for keys. | ☐ |
| Encrypt CJI in the database | If Quarry's backend stores or caches any JNET response data, the database must use encryption at rest (e.g., PostgreSQL with pgcrypto or transparent data encryption). | ☐ |
| Minimize CJI storage | Best practice: don't persist JNET lookup results at all. Display them to the officer and discard. If you must cache, set a short TTL and purge. | ☐ |

---

## 2. Authentication (IA-2, IA-5)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Multi-factor authentication for all accounts accessing CJI — both privileged and non-privileged (IA-2(1), IA-2(2)) | Officers using JNET lookup in BirdDog must authenticate with MFA. Your existing SSO via Microsoft Entra ID supports MFA — ensure it's enforced, not optional, for any session that can trigger a JNET query. | ☐ |
| AAL2 or higher authenticator assurance | Hardware tokens, authenticator apps, or smart cards. SMS-based MFA does NOT qualify. Confirm Entra ID MFA method is compliant (Microsoft Authenticator app = AAL2). | ☐ |
| Replay-resistant authentication (IA-2(8)) | SSO tokens must not be replayable. OAuth 2.0 with PKCE + short-lived access tokens satisfies this. | ☐ |
| Unique user identification — no shared accounts | Every officer must have their own login. No generic "parking" account. Already the case with SSO. | ☐ |
| Password policy (IA-5(1)) | Minimum 8 characters, OR 20+ characters with reduced complexity. Managed by Entra ID — confirm your tenant policy meets this. | ☐ |
| Failed login lockout (AC-7) | Lock account after 5 failed attempts within 15 minutes. Confirm Entra ID enforces this. | ☐ |

---

## 3. Session Management (AC-11, AC-12)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Session timeout after 30 minutes of inactivity | BirdDog must lock or log out the user after 30 minutes idle. Require re-authentication to resume. | ☐ |
| Pattern-hiding display on lock (AC-11(1)) | When the app locks, CJI data must not be visible on screen. Clear any displayed JNET results before showing the lock screen. | ☐ |
| Automatic session termination (AC-12) | Server-side: expire the JNET session token. Client-side: clear CJI from memory on timeout. | ☐ |

---

## 4. Access Control (AC-2, AC-5, AC-6)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Role-based access control | Not every Quarry user should have JNET access. Add a "JNET Lookup" permission/role that administrators assign only to authorized sworn officers and dispatchers. | ☐ |
| Least privilege (AC-6) | The JNET lookup role grants only the ability to query plates/owners. No access to modify JNET data or access other JNET systems beyond what's needed. | ☐ |
| Separation of duties (AC-5) | The person who grants JNET access roles should not be the same person who uses them. Admin vs. officer separation. | ☐ |
| Periodic review of access (AC-6(7)) | Quarterly review of who has JNET lookup privileges. Build a report or admin screen showing current JNET-authorized users. | ☐ |
| Disable inactive accounts (AC-2(5)) | Auto-disable JNET access for users who haven't logged in for a defined period (e.g., 90 days). | ☐ |
| Deny by default (SC-7(5)) | JNET lookup must be explicitly granted. New users get no JNET access until an admin enables it. | ☐ |

---

## 5. Audit Logging (AU-2, AU-3, AU-6)

This is one of the biggest requirements. Every JNET query is auditable by the state.

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Log every JNET query with: date/time, user identity, query type, query parameters (plate number), source IP/device, and result status | Build a dedicated JNET audit log table. Every lookup = one row. | ☐ |
| Include originating agency identifier (IA-0) | Every query must carry Moravian University's ORI (Originating Agency Identifier) number. Get this from your campus police — they have one. | ☐ |
| Limit PII in logs (AU-3(3)) | Log the plate queried and who queried it, but don't store the full JNET response (registered owner SSN, address, etc.) in the audit log. Log success/failure and record count only. | ☐ |
| Restrict log access (AU-9(4)) | Only designated admins can view JNET audit logs. Not the officers themselves. | ☐ |
| Retain logs for minimum 1 year (AU-11) | JNET audit log retention policy: 1 year minimum. Confirm your infrastructure supports this. | ☐ |
| Weekly log review (AU-6) | Someone (campus police supervisor or IT security) must review JNET query logs weekly for anomalies — unusual query volumes, off-hours lookups, queries unrelated to active enforcement. | ☐ |
| Automated alerting (AU-6(1)) | Alert on suspicious patterns: same plate queried repeatedly, queries from unusual locations, queries outside shift hours. | ☐ |

---

## 6. Mobile Device Requirements (Section 5.20)

Since BirdDog is the mobile client, this section applies directly.

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Full device or container encryption (AC-19(5)) | iOS devices have hardware encryption by default when a passcode is set. Require passcode as a prerequisite for BirdDog JNET features. Check `isPasscodeSet` at launch. | ☐ |
| Mobile Device Management (MDM) (5.20.2) | Devices accessing CJI must be managed. Moravian likely uses Jamf or Intune — confirm JNET-capable devices are enrolled and MDM policies enforce encryption, passcode, and remote wipe. | ☐ |
| Remote lock and wipe capability | MDM must be able to remotely lock or wipe a lost/stolen device. Standard MDM capability. | ☐ |
| Jailbreak/root detection | BirdDog must detect jailbroken devices and refuse to perform JNET lookups on them. Add a jailbreak detection check before any JNET query. | ☐ |
| Local device authentication (5.20.7.1) | Require device-level biometric or passcode authentication before JNET lookups, separate from app login. Use LocalAuthentication framework (Face ID/Touch ID). | ☐ |
| Bluetooth restrictions (5.20.1.3) | Document that Bluetooth is used only for Star Micronics printer communication, not for CJI transmission. JNET data never travels over Bluetooth. | ☐ |
| Automatic patching (5.20.4.1) | MDM policy must enforce iOS updates. Document minimum iOS version for JNET features. | ☐ |
| Malicious code protection (5.20.4.2) | iOS App Store distribution + MDM provides this. Document it. | ☐ |

---

## 7. Network and Boundary Protection (SC-7)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Managed access control points (SC-7) | JNET queries from Quarry backend must go through a defined, monitored network path. No direct device-to-JNET connections — BirdDog talks to Quarry backend, Quarry backend talks to JNET. | ☐ |
| No split tunneling (SC-7(7)) | If a VPN is required for JNET access, all traffic must route through it — no split tunneling. | ☐ |
| Deny by default firewall rules (SC-7(5)) | Quarry's server must have firewall rules that allow only the specific JNET web service endpoints and deny everything else on that interface. | ☐ |
| DNS security (SC-20, SC-21, SC-22) | Use DNSSEC-validating resolvers for JNET endpoint resolution. | ☐ |

---

## 8. Incident Response (IR-4, IR-6)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Written incident response plan | Document what happens if CJI is breached: who is notified, containment steps, evidence preservation. | ☐ |
| Report incidents to FBI CJIS ISO | Any breach of CJI must be reported to the CJIS Information Security Officer. Know who your state CSA (CJIS Systems Agency) contact is — in PA, that's the Pennsylvania State Police. | ☐ |
| Automated incident detection (IR-4(1)) | Monitor for unauthorized access attempts to the JNET integration endpoint. Alert on failures and anomalies. | ☐ |
| Breach-specific response plan (IR-8(1)) | Separate from general incident response. Specific to CJI data exposure: what data was exposed, whose records, notification obligations. | ☐ |

---

## 9. Personnel Security (PS-3, PS-6)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Fingerprint-based background check | Every person with unescorted access to CJI — including developers who can see production JNET data — must pass a fingerprint-based background screening. | ☐ |
| Access agreements | Signed agreements from every person with CJI access acknowledging their responsibilities. | ☐ |
| Security awareness training (AT-2) | Annual CJIS security awareness training for all personnel with CJI access. | ☐ |
| Termination procedures (PS-4) | When an officer or developer leaves, immediately revoke JNET access and recover any devices. | ☐ |

---

## 10. Configuration and Vulnerability Management (CM, RA-5)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Baseline configuration (CM-2) | Document the exact server configuration, software versions, and network settings for the JNET integration components. | ☐ |
| Change control (CM-3) | Any changes to the JNET integration code or infrastructure must go through a documented change management process with testing before deployment. | ☐ |
| Least functionality (CM-7) | The server handling JNET queries should run only the services needed for that function. No unnecessary ports, protocols, or software. | ☐ |
| Vulnerability scanning (RA-5) | Regular vulnerability scans of the Quarry infrastructure that handles CJI. Priority 1 — sanctionable now. | ☐ |
| Software inventory (CM-8) | Maintain an inventory of all software components in the JNET integration path, including dependencies. | ☐ |

---

## 11. Information Exchange Agreement (Policy Area 1)

| Requirement | What Quarry/BirdDog Needs | Status |
|---|---|---|
| Formal agreement with JNET | Execute an Information Exchange Agreement or Memorandum of Understanding with JNET/PA State Police specifying what data you access, how it's protected, and who is responsible. | ☐ |
| Document security controls in agreement | The agreement must specify all the controls above — encryption standards, audit logging, access control, incident response, personnel security. | ☐ |
| Specify functions, ports, protocols (SA-9(2)) | Document exactly which JNET web services you call, which ports and protocols you use, and how the data flows. | ☐ |

---

## Architecture Recommendation

```
Officer (BirdDog iOS)
    |
    | HTTPS/TLS 1.2+ (FIPS validated)
    |
Quarry Backend (your server)
    |
    | HTTPS/TLS 1.2+ to JNET web services
    | (authenticated with JNET-issued certificates)
    |
JNET Web Services
    |
    | PennDOT / NCIC / NLETS
```

Key points:
- BirdDog never talks directly to JNET — all queries proxy through Quarry backend
- Quarry backend handles JNET authentication (likely mutual TLS with a JNET-issued client certificate)
- CJI data is displayed to the officer and not persisted
- Every query is audit-logged server-side with user identity, timestamp, plate, and ORI

---

## Before You Pitch: Gap Assessment

Review each checkbox above against your current Quarry/BirdDog implementation. The most likely gaps for a new integration are:

1. **Audit logging** — you probably don't have JNET-specific audit logging yet
2. **Session timeout** — verify BirdDog enforces 30-minute idle lockout
3. **Jailbreak detection** — probably not implemented yet
4. **Personnel background checks** — developers with production access need fingerprinting
5. **MDM enrollment** — confirm enforcement devices are managed
6. **Formal agreements** — the MOU with JNET/PA State Police takes time
7. **Weekly log review process** — operational, not technical, but required

Most of the encryption and authentication requirements are likely already met through iOS platform security and your Entra ID SSO setup. The gaps are in the CJIS-specific operational controls.
