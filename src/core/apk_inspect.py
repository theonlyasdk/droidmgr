"""Static APK inspection: manifest components and signing certificates."""

from __future__ import annotations

import hashlib
import os
import struct
import zipfile
from typing import Any, Dict, List
from .apk_format import TYPE_INT_BOOLEAN, TYPE_INT_DEC, TypedValue
from .apk_binxml import parse_binary_xml_elements


# --- APK Static Inspector (Manifest, Components, Signatures) -----------------

def parse_asn1_length(data: bytes, offset: int) -> Tuple[int, int]:
    if offset >= len(data):
        return 0, offset
    first = data[offset]
    if first < 0x80:
        return first, offset + 1
    num_bytes = first & 0x7F
    if offset + 1 + num_bytes > len(data):
        return 0, offset + 1
    val = 0
    for b in data[offset + 1:offset + 1 + num_bytes]:
        val = (val << 8) | b
    return val, offset + 1 + num_bytes


def parse_asn1_tag(data: bytes, offset: int) -> Tuple[Optional[int], int, int]:
    if offset >= len(data):
        return None, 0, offset
    tag = data[offset]
    length, content_offset = parse_asn1_length(data, offset + 1)
    return tag, length, content_offset


def _decode_x509_name(name_bytes: bytes) -> str:
    oids = {
        b'\x55\x04\x03': 'CN',
        b'\x55\x04\x06': 'C',
        b'\x55\x04\x07': 'L',
        b'\x55\x04\x08': 'ST',
        b'\x55\x04\x0a': 'O',
        b'\x55\x04\x0b': 'OU',
        b'\x2a\x86\x48\x86\xf7\x0d\x01\x09\x01': 'EMAIL'
    }
    parts = []
    for oid, label in oids.items():
        pos = name_bytes.find(oid)
        if pos >= 0:
            val_offset = pos + len(oid)
            if val_offset < len(name_bytes):
                _, vl, vcont = parse_asn1_tag(name_bytes, val_offset)
                str_val = name_bytes[vcont:vcont + vl].decode('utf-8', errors='replace')
                if str_val:
                    parts.append(f'{label}={str_val}')
    return ', '.join(parts) if parts else 'Unknown'


def parse_x509_der(cert_bytes: bytes) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        'sha256': ':'.join(f'{b:02X}' for b in hashlib.sha256(cert_bytes).digest()),
        'sha1': ':'.join(f'{b:02X}' for b in hashlib.sha1(cert_bytes).digest()),
        'md5': ':'.join(f'{b:02X}' for b in hashlib.md5(cert_bytes).digest()),
        'serial': 'Unknown',
        'subject': 'Unknown',
        'issuer': 'Unknown',
        'valid_from': '',
        'valid_to': '',
    }
    try:
        _, _, off = parse_asn1_tag(cert_bytes, 0)
        _, _, tbs_off = parse_asn1_tag(cert_bytes, off)
        cur = tbs_off

        if cur < len(cert_bytes) and cert_bytes[cur] == 0xA0:
            _, l, cur = parse_asn1_tag(cert_bytes, cur)
            cur += l  # Skip version

        # Serial number
        _, l, cur = parse_asn1_tag(cert_bytes, cur)
        info['serial'] = cert_bytes[cur:cur + l].hex().upper()
        cur += l

        # Signature algorithm
        _, l, cur = parse_asn1_tag(cert_bytes, cur)
        cur += l

        # Issuer
        _, issuer_len, cur = parse_asn1_tag(cert_bytes, cur)
        info['issuer'] = _decode_x509_name(cert_bytes[cur:cur + issuer_len])
        cur += issuer_len

        # Validity
        _, val_len, cur = parse_asn1_tag(cert_bytes, cur)
        val_bytes = cert_bytes[cur:cur + val_len]
        cur += val_len
        try:
            _, vl1, vo1 = parse_asn1_tag(val_bytes, 0)
            d1 = val_bytes[vo1:vo1 + vl1].decode('ascii', errors='ignore')
            _, vl2, vo2 = parse_asn1_tag(val_bytes, vo1 + vl1)
            d2 = val_bytes[vo2:vo2 + vl2].decode('ascii', errors='ignore')
            info['valid_from'] = d1
            info['valid_to'] = d2
        except Exception:
            pass

        # Subject
        _, subj_len, cur = parse_asn1_tag(cert_bytes, cur)
        info['subject'] = _decode_x509_name(cert_bytes[cur:cur + subj_len])
    except Exception:
        pass

    return info


def find_x509_certs_in_pkcs7(data: bytes) -> List[bytes]:
    certs: List[bytes] = []
    i = 0
    while i < len(data) - 4:
        if data[i] == 0x30:
            cert_len, len_offset = parse_asn1_length(data, i + 1)
            if cert_len > 100 and i + len_offset + cert_len <= len(data):
                sub_i = i + len_offset
                if sub_i < len(data) and data[sub_i] == 0x30:
                    cert_data = data[i:i + len_offset + cert_len]
                    certs.append(cert_data)
                    i += len_offset + cert_len
                    continue
        i += 1
    return certs


def parse_apk_signatures(apk_path: str) -> Dict[str, Any]:
    sig_info: Dict[str, Any] = {
        'schemes': [],
        'certificates': [],
    }
    if not os.path.isfile(apk_path):
        return sig_info

    # 1. Check v1 (JAR signing)
    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            meta_sig_files = [
                n for n in zf.namelist()
                if n.upper().startswith('META-INF/') and any(n.upper().endswith(ext) for ext in ('.RSA', '.DSA', '.EC'))
            ]
            if meta_sig_files:
                sig_info['schemes'].append('v1 (JAR)')
                for mf in meta_sig_files:
                    try:
                        raw = zf.read(mf)
                        found_certs = find_x509_certs_in_pkcs7(raw)
                        for c in found_certs:
                            parsed = parse_x509_der(c)
                            parsed['scheme'] = 'v1'
                            parsed['source'] = mf
                            sig_info['certificates'].append(parsed)
                    except Exception:
                        pass
    except Exception:
        pass

    # 2. Check APK Signing Block (v2, v3, v3.1)
    try:
        with open(apk_path, 'rb') as f:
            f.seek(0, 2)
            flen = f.tell()
            f.seek(max(0, flen - 65536))
            tail = f.read()
            idx = tail.rfind(b'PK\x05\x06')
            if idx >= 0:
                cd_offset = struct.unpack('<I', tail[idx + 16:idx + 20])[0]
                if cd_offset >= 24:
                    f.seek(cd_offset - 24)
                    bsize, magic = struct.unpack('<Q16s', f.read(24))
                    if magic == b'APK Sig Block 42':
                        f.seek(cd_offset - bsize)
                        end_of_pairs = cd_offset - 24
                        while f.tell() < end_of_pairs:
                            pair_len = struct.unpack('<Q', f.read(8))[0]
                            pair_id = struct.unpack('<I', f.read(4))[0]
                            pair_val = f.read(pair_len - 4)

                            scheme_label = None
                            if pair_id == 0x7109871a:
                                scheme_label = 'v2'
                                if 'v2' not in sig_info['schemes']:
                                    sig_info['schemes'].append('v2')
                            elif pair_id == 0xf05368c0:
                                scheme_label = 'v3'
                                if 'v3' not in sig_info['schemes']:
                                    sig_info['schemes'].append('v3')
                            elif pair_id == 0x1b93ad61:
                                scheme_label = 'v3.1'
                                if 'v3.1' not in sig_info['schemes']:
                                    sig_info['schemes'].append('v3.1')

                            if scheme_label and len(pair_val) >= 4:
                                try:
                                    pos = 4
                                    while pos < len(pair_val):
                                        signer_len = struct.unpack('<I', pair_val[pos:pos + 4])[0]
                                        signer = pair_val[pos + 4:pos + 4 + signer_len]
                                        pos += 4 + signer_len
                                        sd_len = struct.unpack('<I', signer[0:4])[0]
                                        sd = signer[4:4 + sd_len]
                                        dig_len = struct.unpack('<I', sd[0:4])[0]
                                        c_offset = 4 + dig_len
                                        certs_len = struct.unpack('<I', sd[c_offset:c_offset + 4])[0]
                                        c_pos = c_offset + 4
                                        while c_pos < c_offset + 4 + certs_len:
                                            cert_len = struct.unpack('<I', sd[c_pos:c_pos + 4])[0]
                                            cert_bytes = sd[c_pos + 4:c_pos + 4 + cert_len]
                                            c_pos += 4 + cert_len
                                            parsed = parse_x509_der(cert_bytes)
                                            parsed['scheme'] = scheme_label
                                            sig_info['certificates'].append(parsed)
                                except Exception:
                                    pass
    except Exception:
        pass

    return sig_info


def parse_apk_manifest(manifest_bytes: bytes) -> Dict[str, Any]:
    res: Dict[str, Any] = {
        'package': '',
        'version_name': '',
        'version_code': '',
        'min_sdk': '',
        'target_sdk': '',
        'compile_sdk': '',
        'debuggable': False,
        'permissions': [],
        'activities': [],
        'services': [],
        'receivers': [],
        'providers': [],
    }
    for event, name, attrs in parse_binary_xml_elements(manifest_bytes):
        if event != 'start':
            continue
        tag_low = (name or '').lower()
        if tag_low == 'manifest':
            res['package'] = attrs.get('package', TypedValue(0, 0, '')).string or ''
            vc = attrs.get('versionCode') or attrs.get('id:0x0101021b')
            if vc:
                res['version_code'] = str(vc.data if vc.data_type == TYPE_INT_DEC else (vc.string or vc.data))
            vn = attrs.get('versionName') or attrs.get('id:0x0101021c')
            if vn:
                res['version_name'] = str(vn.string or vn.data)
            cs = attrs.get('compileSdkVersion') or attrs.get('id:0x01010572')
            if cs:
                res['compile_sdk'] = str(cs.data if cs.data_type == TYPE_INT_DEC else (cs.string or cs.data))
        elif tag_low == 'uses-sdk':
            ms = attrs.get('minSdkVersion') or attrs.get('id:0x0101020c')
            if ms:
                res['min_sdk'] = str(ms.data if ms.data_type == TYPE_INT_DEC else (ms.string or ms.data))
            ts = attrs.get('targetSdkVersion') or attrs.get('id:0x01010270')
            if ts:
                res['target_sdk'] = str(ts.data if ts.data_type == TYPE_INT_DEC else (ts.string or ts.data))
        elif tag_low == 'application':
            dbg = attrs.get('debuggable') or attrs.get('id:0x01010000')
            if dbg:
                res['debuggable'] = bool(dbg.data) if dbg.data_type in (TYPE_INT_BOOLEAN, TYPE_INT_DEC) else (str(dbg.string).lower() == 'true')
        elif tag_low == 'uses-permission':
            pname = attrs.get('name') or attrs.get('id:0x01010003')
            if pname and (pname.string or pname.data):
                val = pname.string or str(pname.data)
                if val not in res['permissions']:
                    res['permissions'].append(val)
        elif tag_low in ('activity', 'activity-alias'):
            aname = attrs.get('name') or attrs.get('id:0x01010003')
            if aname and (aname.string or aname.data):
                val = aname.string or str(aname.data)
                if val not in res['activities']:
                    res['activities'].append(val)
        elif tag_low == 'service':
            sname = attrs.get('name') or attrs.get('id:0x01010003')
            if sname and (sname.string or sname.data):
                val = sname.string or str(sname.data)
                if val not in res['services']:
                    res['services'].append(val)
        elif tag_low == 'receiver':
            rname = attrs.get('name') or attrs.get('id:0x01010003')
            if rname and (rname.string or rname.data):
                val = rname.string or str(rname.data)
                if val not in res['receivers']:
                    res['receivers'].append(val)
        elif tag_low == 'provider':
            prname = attrs.get('name') or attrs.get('id:0x01010003')
            if prname and (prname.string or prname.data):
                val = prname.string or str(prname.data)
                if val not in res['providers']:
                    res['providers'].append(val)

    return res


def inspect_apk(apk_path: str) -> Dict[str, Any]:
    """Statically parse a local .apk file without installation or AAPT."""
    out: Dict[str, Any] = {
        'file_path': apk_path,
        'file_size': 0,
        'file_name': os.path.basename(apk_path),
        'dex_count': 0,
        'package': '',
        'version_name': '',
        'version_code': '',
        'min_sdk': '',
        'target_sdk': '',
        'compile_sdk': '',
        'debuggable': False,
        'permissions': [],
        'activities': [],
        'services': [],
        'receivers': [],
        'providers': [],
        'schemes': [],
        'certificates': [],
    }
    if not os.path.isfile(apk_path):
        return out

    out['file_size'] = os.path.getsize(apk_path)

    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            dex_files = [n for n in zf.namelist() if n.endswith('.dex')]
            out['dex_count'] = len(dex_files)
            if 'AndroidManifest.xml' in zf.namelist():
                manifest_bytes = zf.read('AndroidManifest.xml')
                manifest_data = parse_apk_manifest(manifest_bytes)
                out.update(manifest_data)
    except Exception:
        pass

    sig_data = parse_apk_signatures(apk_path)
    out['schemes'] = sig_data.get('schemes', [])
    out['certificates'] = sig_data.get('certificates', [])

    return out
