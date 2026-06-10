#!/usr/bin/env python3
"""
Análisis completo del Google Spreadsheet de agenda de turnos.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, date

FILE_PATH = "/root/.claude/projects/-home-user-Agendadeturnos/93e9ece5-6151-5ee7-bfd3-eb793a7394be/tool-results/mcp-Google_Drive-read_file_content-1781114895389.txt"

def parse_file(path):
    """Lee el archivo JSON y extrae fileContent."""
    with open(path, 'r', encoding='utf-8') as f:
        raw = f.read()
    # El archivo es JSON con campo fileContent
    data = json.loads(raw)
    return data['fileContent']

def split_sheets(content):
    """
    El contenido markdown tiene múltiples hojas separadas.
    Buscamos separadores de hoja (líneas con '---' o encabezados de hoja).
    Retorna dict {sheet_name: [rows_as_lists]}
    """
    sheets = {}
    # Primero detectar qué hojas hay buscando patrones de tabla markdown
    # Las hojas están separadas — buscar por nombre de hoja si existe
    # Dividimos por bloques de tabla markdown

    lines = content.split('\n')
    current_sheet = None
    current_rows = []
    sheet_order = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Detectar nombre de hoja (línea con ## o similar, o línea que precede tabla)
        if line.startswith('##'):
            # Guardar hoja anterior
            if current_sheet and current_rows:
                sheets[current_sheet] = current_rows
            current_sheet = line.lstrip('#').strip()
            sheet_order.append(current_sheet)
            current_rows = []
            i += 1
            continue

        # Líneas de tabla markdown
        if line.startswith('|'):
            if current_sheet is None:
                current_sheet = 'Sheet1'
                sheet_order.append(current_sheet)
            cells = [c.strip() for c in line.split('|')[1:-1]]
            current_rows.append(cells)

        i += 1

    if current_sheet and current_rows:
        sheets[current_sheet] = current_rows

    return sheets, sheet_order

def rows_to_dicts(rows):
    """Convierte lista de rows (primera = headers) a lista de dicts."""
    if not rows:
        return []
    # Encontrar header row (la que no es separador --- )
    header_idx = None
    for idx, row in enumerate(rows):
        if not all(set(c.replace('-','').replace(':','').strip()) <= {''} for c in row):
            header_idx = idx
            break
    if header_idx is None:
        return []

    headers = rows[header_idx]
    result = []
    for row in rows[header_idx+1:]:
        # Skip separator rows
        if all(set(c.replace('-','').replace(':','').strip()) <= {''} for c in row):
            continue
        # Align columns
        d = {}
        for j, h in enumerate(headers):
            d[h] = row[j] if j < len(row) else ''
        result.append(d)
    return result

def normalize_rut(rut):
    """Normaliza RUT eliminando puntos, guiones, espacios."""
    if not rut:
        return ''
    return re.sub(r'[\.\-\s]', '', rut).upper().strip()

def parse_date_turno(date_str):
    """Parsea fecha de turno en formato YYYY-MM-DD o similar."""
    if not date_str:
        return None
    date_str = date_str.strip()
    # Intentar varios formatos
    for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d']:
        try:
            return datetime.strptime(date_str, fmt).date()
        except:
            pass
    # Intentar extraer fecha con regex
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_str)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r'(\d{2})/(\d{2})/(\d{4})', date_str)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None

def parse_enrolled(enrolled_str):
    """Parsea el JSON de enrolled."""
    if not enrolled_str or enrolled_str.strip() in ('', '[]', 'null'):
        return []
    s = enrolled_str.strip()
    # Puede tener escapes markdown
    s = s.replace('\\n', '\n').replace('\\"', '"')
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return data
        return []
    except:
        # Intentar extraer pares rut/name con regex
        persons = []
        pattern = r'"rut"\s*:\s*"([^"]+)".*?"name"\s*:\s*"([^"]+)"'
        for m in re.finditer(pattern, s, re.DOTALL):
            persons.append({'rut': m.group(1), 'name': m.group(2)})
        if not persons:
            pattern2 = r'"name"\s*:\s*"([^"]+)".*?"rut"\s*:\s*"([^"]+)"'
            for m in re.finditer(pattern2, s, re.DOTALL):
                persons.append({'rut': m.group(2), 'name': m.group(1)})
        return persons

def find_column(headers, candidates):
    """Encuentra el primer header que coincide con alguno de los candidatos (case insensitive)."""
    hl = [h.lower().strip() for h in headers]
    for c in candidates:
        for i, h in enumerate(hl):
            if c.lower() in h:
                return headers[i]
    return None

def main():
    print("=" * 80)
    print("ANÁLISIS COMPLETO DE AGENDA DE TURNOS")
    print("=" * 80)

    # 1. Leer archivo
    print("\n[Leyendo archivo...]")
    content = parse_file(FILE_PATH)
    print(f"  Contenido leído: {len(content):,} caracteres")

    # 2. Dividir en hojas
    sheets, sheet_order = split_sheets(content)
    print(f"\n  Hojas detectadas: {list(sheets.keys())}")
    for sname, rows in sheets.items():
        print(f"    '{sname}': {len(rows)} filas raw")

    # Identificar hojas clave
    # Buscar hoja de turnos (tiene columna enrolled o shift)
    # Buscar hoja inscritos (tiene columna RUT e ID Turno)

    turnos_sheet = None
    inscritos_sheet = None

    for sname, rows in sheets.items():
        if len(rows) < 2:
            continue
        # Obtener headers (primera fila no separadora)
        header_row = None
        for r in rows:
            if not all(set(c.replace('-','').replace(':','').strip()) <= {''} for c in r):
                header_row = r
                break
        if not header_row:
            continue
        headers_lower = ' '.join(h.lower() for h in header_row)

        if 'enrolled' in headers_lower or 'shift' in headers_lower or 'branch' in headers_lower:
            turnos_sheet = sname
        if 'rut' in headers_lower and ('id turno' in headers_lower or 'id_turno' in headers_lower or 'turno' in headers_lower):
            inscritos_sheet = sname

    print(f"\n  Hoja turnos identificada: '{turnos_sheet}'")
    print(f"  Hoja inscritos identificada: '{inscritos_sheet}'")

    # Obtener dicts
    turnos_rows = rows_to_dicts(sheets.get(turnos_sheet, [])) if turnos_sheet else []
    inscritos_rows = rows_to_dicts(sheets.get(inscritos_sheet, [])) if inscritos_sheet else []

    print(f"\n  Registros en hoja turnos: {len(turnos_rows)}")
    print(f"  Registros en hoja inscritos: {len(inscritos_rows)}")

    # Mostrar columnas disponibles
    if turnos_rows:
        print(f"\n  Columnas hoja turnos: {list(turnos_rows[0].keys())}")
    if inscritos_rows:
        print(f"  Columnas hoja inscritos: {list(inscritos_rows[0].keys())}")

    # -------------------------------------------------------------------------
    # ANÁLISIS 1: Turnos activos con enrolled
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("ANÁLISIS 1: TURNOS CON PERSONAS INSCRITAS (enrolled)")
    print("=" * 80)

    # Detectar columnas
    if turnos_rows:
        tcols = list(turnos_rows[0].keys())
        col_id = find_column(tcols, ['id'])
        col_branch = find_column(tcols, ['branch', 'sucursal'])
        col_shift = find_column(tcols, ['shift', 'turno'])
        col_date = find_column(tcols, ['date', 'fecha'])
        col_limit = find_column(tcols, ['limit', 'limite', 'cupo'])
        col_enrolled = find_column(tcols, ['enrolled', 'inscritos'])
        print(f"\n  Columnas mapeadas:")
        print(f"    id={col_id}, branch={col_branch}, shift={col_shift}, date={col_date}, limit={col_limit}, enrolled={col_enrolled}")
    else:
        col_id = col_branch = col_shift = col_date = col_limit = col_enrolled = None

    CUT_DATE = date(2026, 6, 1)

    turnos_activos = []  # list of dicts con info de turno + personas
    turnos_con_enrolled = 0
    total_enrolled_personas = 0

    for row in turnos_rows:
        sid = row.get(col_id, '').strip() if col_id else ''
        branch = row.get(col_branch, '').strip() if col_branch else ''
        shift = row.get(col_shift, '').strip() if col_shift else ''
        date_str = row.get(col_date, '').strip() if col_date else ''
        limit = row.get(col_limit, '').strip() if col_limit else ''
        enrolled_str = row.get(col_enrolled, '').strip() if col_enrolled else ''

        enrolled = parse_enrolled(enrolled_str)
        if not enrolled:
            continue

        turno_date = parse_date_turno(date_str)

        turnos_con_enrolled += 1
        total_enrolled_personas += len(enrolled)

        turnos_activos.append({
            'id': sid,
            'branch': branch,
            'shift': shift,
            'date': turno_date,
            'date_str': date_str,
            'limit': limit,
            'enrolled': enrolled,
        })

    print(f"\n  Turnos con enrolled no vacío: {turnos_con_enrolled}")
    print(f"  Total personas en enrolled (todos los turnos): {total_enrolled_personas}")

    # Filtrar >= Jun 2026
    turnos_jun = [t for t in turnos_activos if t['date'] and t['date'] >= CUT_DATE]
    turnos_jun_enrolled = sum(len(t['enrolled']) for t in turnos_jun)

    print(f"\n  Turnos >= 2026-06-01: {len(turnos_jun)}")
    print(f"  Total personas en enrolled (>= Jun 2026): {turnos_jun_enrolled}")

    print(f"\n  {'ShiftID':<12} {'Branch':<25} {'Fecha':<12} {'Limit':<6} {'#Inscritos':<10} Personas")
    print(f"  {'-'*12} {'-'*25} {'-'*12} {'-'*6} {'-'*10} {'-'*30}")
    for t in sorted(turnos_jun, key=lambda x: (x['date'] or date.min, x['branch'])):
        persons_str = ', '.join(f"{p.get('name','?')} ({p.get('rut','?')})" for p in t['enrolled'])
        print(f"  {t['id']:<12} {t['branch']:<25} {str(t['date']):<12} {t['limit']:<6} {len(t['enrolled']):<10} {persons_str}")

    # -------------------------------------------------------------------------
    # ANÁLISIS 2: Hoja Inscritos
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("ANÁLISIS 2: HOJA INSCRITOS")
    print("=" * 80)

    if inscritos_rows:
        icols = list(inscritos_rows[0].keys())
        print(f"\n  Columnas: {icols}")

        col_irut = find_column(icols, ['rut'])
        col_iname = find_column(icols, ['nombre', 'name'])
        col_iturno = find_column(icols, ['id turno', 'id_turno', 'turno', 'shift'])
        col_ifecha = find_column(icols, ['fecha inscripcion', 'fecha', 'date'])
        col_ibranch = find_column(icols, ['branch', 'sucursal'])

        print(f"\n  Columnas mapeadas:")
        print(f"    rut={col_irut}, nombre={col_iname}, id_turno={col_iturno}, fecha={col_ifecha}, branch={col_ibranch}")
    else:
        col_irut = col_iname = col_iturno = col_ifecha = col_ibranch = None

    # Set de (rut_norm, shift_id) en inscritos
    inscritos_set = set()
    inscritos_data = []  # lista de dicts con info

    for row in inscritos_rows:
        rut = row.get(col_irut, '').strip() if col_irut else ''
        name = row.get(col_iname, '').strip() if col_iname else ''
        shift_id = row.get(col_iturno, '').strip() if col_iturno else ''
        fecha = row.get(col_ifecha, '').strip() if col_ifecha else ''
        branch = row.get(col_ibranch, '').strip() if col_ibranch else ''

        rut_norm = normalize_rut(rut)

        if rut_norm or shift_id:
            inscritos_set.add((rut_norm, shift_id))
            inscritos_data.append({
                'rut': rut,
                'rut_norm': rut_norm,
                'name': name,
                'shift_id': shift_id,
                'fecha': fecha,
                'branch': branch,
                'row': row
            })

    print(f"\n  Total filas en hoja Inscritos: {len(inscritos_data)}")

    # Filtrar >= Jun 2026 usando shift_id para cruzar con turnos_jun
    turnos_jun_ids = {t['id'] for t in turnos_jun}
    inscritos_jun = [i for i in inscritos_data if i['shift_id'] in turnos_jun_ids]
    print(f"  Filas en Inscritos con shift_id en turnos >= Jun 2026: {len(inscritos_jun)}")

    # También intentar filtrar por fecha
    def parse_fecha_inscripcion(s):
        if not s:
            return None
        for fmt in ['%d/%m/%Y %H:%M:%S', '%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
            try:
                return datetime.strptime(s.strip(), fmt).date()
            except:
                pass
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return None

    inscritos_jun_byfecha = [i for i in inscritos_data
                              if parse_fecha_inscripcion(i['fecha']) and
                              parse_fecha_inscripcion(i['fecha']) >= CUT_DATE]
    print(f"  Filas en Inscritos con fecha inscripción >= Jun 2026: {len(inscritos_jun_byfecha)}")

    # -------------------------------------------------------------------------
    # ANÁLISIS 3: CRUCE - personas en enrolled SIN fila en Inscritos
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("ANÁLISIS 3: PERSONAS EN ENROLLED SIN FILA EN INSCRITOS (>= Jun 2026)")
    print("=" * 80)

    faltantes = []

    for t in turnos_jun:
        for p in t['enrolled']:
            rut = p.get('rut', '')
            name = p.get('name', '')
            rut_norm = normalize_rut(rut)
            shift_id = t['id']

            # Verificar si existe (rut_norm, shift_id) en inscritos
            found = (rut_norm, shift_id) in inscritos_set

            if not found:
                # También buscar solo por rut_norm entre inscritos de ese turno
                found_by_rut = any(
                    i['rut_norm'] == rut_norm and i['shift_id'] == shift_id
                    for i in inscritos_data
                )
                if not found_by_rut:
                    faltantes.append({
                        'rut': rut,
                        'rut_norm': rut_norm,
                        'name': name,
                        'branch': t['branch'],
                        'date': t['date'],
                        'shift_id': shift_id,
                    })

    print(f"\n  Personas en enrolled SIN fila en Inscritos: {len(faltantes)}")

    if faltantes:
        print(f"\n  {'RUT':<18} {'Nombre':<35} {'Sucursal':<25} {'Fecha':<12} {'ShiftID'}")
        print(f"  {'-'*18} {'-'*35} {'-'*25} {'-'*12} {'-'*12}")
        for f in sorted(faltantes, key=lambda x: (x['date'] or date.min, x['branch'], x['name'])):
            print(f"  {f['rut']:<18} {f['name']:<35} {f['branch']:<25} {str(f['date']):<12} {f['shift_id']}")
    else:
        print("  (ninguno)")

    # -------------------------------------------------------------------------
    # ANÁLISIS 4: DUPLICADOS en enrolled
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("ANÁLISIS 4: DUPLICADOS EN ENROLLED")
    print("=" * 80)

    # Para cada rut_norm, buscar si aparece en más de un turno el mismo día
    # Clave: (rut_norm, date)
    rut_date_turnos = defaultdict(list)  # (rut_norm, date) -> list of turno dicts

    for t in turnos_activos:  # todos los turnos, no solo jun
        for p in t['enrolled']:
            rut = p.get('rut', '')
            name = p.get('name', '')
            rut_norm = normalize_rut(rut)
            key = (rut_norm, t['date'])
            rut_date_turnos[key].append({
                'rut': rut,
                'name': name,
                'shift_id': t['id'],
                'branch': t['branch'],
                'date': t['date'],
                'shift': t['shift'],
            })

    dup_misma_sucursal = []  # mismo día, misma sucursal, distintos IDs
    dup_dist_sucursal = []   # mismo día, distintas sucursales

    for (rut_norm, d), entries in rut_date_turnos.items():
        if len(entries) < 2:
            continue

        # Agrupar por branch
        branches = set(e['branch'] for e in entries)
        shift_ids = set(e['shift_id'] for e in entries)

        if len(shift_ids) < 2:
            continue  # misma persona en mismo turno registrada una vez (no duplicado)

        if len(branches) == 1:
            dup_misma_sucursal.append((rut_norm, d, entries))
        else:
            dup_dist_sucursal.append((rut_norm, d, entries))

    print(f"\n  Duplicados mismo día + misma sucursal (IDs distintos): {len(dup_misma_sucursal)}")
    if dup_misma_sucursal:
        for rut_norm, d, entries in sorted(dup_misma_sucursal, key=lambda x: (x[1] or date.min,)):
            print(f"\n    RUT: {entries[0]['rut']} | Nombre: {entries[0]['name']} | Fecha: {d}")
            for e in entries:
                print(f"      ShiftID={e['shift_id']} | Branch={e['branch']} | Shift={e['shift']}")

    print(f"\n  Duplicados mismo día + distintas sucursales (conflicto físico): {len(dup_dist_sucursal)}")
    if dup_dist_sucursal:
        for rut_norm, d, entries in sorted(dup_dist_sucursal, key=lambda x: (x[1] or date.min,)):
            print(f"\n    RUT: {entries[0]['rut']} | Nombre: {entries[0]['name']} | Fecha: {d}")
            for e in entries:
                print(f"      ShiftID={e['shift_id']} | Branch={e['branch']} | Shift={e['shift']}")

    if not dup_misma_sucursal and not dup_dist_sucursal:
        print("  (ninguno)")

    # -------------------------------------------------------------------------
    # ANÁLISIS 5: DUPLICADOS en hoja Inscritos
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("ANÁLISIS 5: DUPLICADOS EN HOJA INSCRITOS")
    print("=" * 80)

    # 5a: (RUT, shiftId) duplicado
    pair_count = defaultdict(list)
    for i, ins in enumerate(inscritos_data):
        key = (ins['rut_norm'], ins['shift_id'])
        pair_count[key].append(ins)

    dup_pair = [(k, v) for k, v in pair_count.items() if len(v) > 1 and k[0]]

    print(f"\n  5a. Pares (RUT, ShiftID) duplicados en Inscritos: {len(dup_pair)}")
    if dup_pair:
        for (rut_norm, sid), entries in sorted(dup_pair):
            print(f"\n    RUT: {entries[0]['rut']} | ShiftID: {sid} | Aparece {len(entries)} veces")
            for e in entries:
                print(f"      Nombre: {e['name']} | Fecha inscripcion: {e['fecha']} | Branch: {e['branch']}")
    else:
        print("  (ninguno)")

    # 5b: RUT en mismo día distintas sucursales en hoja Inscritos
    # Necesitamos fecha del turno para cada fila de inscritos
    turno_date_map = {t['id']: t for t in turnos_activos}

    rut_date_inscritos = defaultdict(list)
    for ins in inscritos_data:
        t_info = turno_date_map.get(ins['shift_id'])
        t_date = t_info['date'] if t_info else None
        if not t_date:
            # intentar por fecha inscripcion
            t_date = parse_fecha_inscripcion(ins['fecha'])
        key = (ins['rut_norm'], t_date)
        rut_date_inscritos[key].append(ins)

    dup_inscritos_branch = []
    for (rut_norm, d), entries in rut_date_inscritos.items():
        if len(entries) < 2 or not rut_norm:
            continue
        shift_ids_i = set(e['shift_id'] for e in entries)
        if len(shift_ids_i) < 2:
            continue
        branches_i = set(e['branch'] or (turno_date_map.get(e['shift_id'], {}).get('branch', '') if turno_date_map.get(e['shift_id']) else '') for e in entries)
        dup_inscritos_branch.append((rut_norm, d, entries))

    print(f"\n  5b. RUT con mismo día en distintos turnos (hoja Inscritos): {len(dup_inscritos_branch)}")
    if dup_inscritos_branch:
        for rut_norm, d, entries in sorted(dup_inscritos_branch, key=lambda x: (x[1] or date.min,)):
            print(f"\n    RUT: {entries[0]['rut']} | Nombre: {entries[0]['name']} | Fecha: {d}")
            for e in entries:
                t_info = turno_date_map.get(e['shift_id'], {})
                branch = e['branch'] or (t_info.get('branch', '') if t_info else '')
                print(f"      ShiftID={e['shift_id']} | Branch={branch} | Fecha inscripcion={e['fecha']}")
    else:
        print("  (ninguno)")

    # -------------------------------------------------------------------------
    # RESULTADO FINAL
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("RESULTADO FINAL - RESUMEN EJECUTIVO")
    print("=" * 80)

    print(f"""
  1. Total inscritos en turnos activos (enrolled, Jun 2026 en adelante):
     {turnos_jun_enrolled} personas en {len(turnos_jun)} turnos

  2. Total filas en hoja Inscritos (Jun 2026 en adelante):
     Por shift_id en turnos Jun: {len(inscritos_jun)} filas
     Por fecha inscripción >= Jun 2026: {len(inscritos_jun_byfecha)} filas
     Total filas hoja Inscritos (todos): {len(inscritos_data)} filas

  3. Personas en enrolled NO en hoja Inscritos: {len(faltantes)}
""")

    if faltantes:
        print(f"  {'RUT':<18} {'Nombre':<35} {'Sucursal':<25} {'Fecha':<12} {'ShiftID'}")
        print(f"  {'-'*18} {'-'*35} {'-'*25} {'-'*12} {'-'*12}")
        for f in sorted(faltantes, key=lambda x: (x['date'] or date.min, x['branch'], x['name'])):
            print(f"  {f['rut']:<18} {f['name']:<35} {f['branch']:<25} {str(f['date']):<12} {f['shift_id']}")

    print(f"\n  4. Duplicados en enrolled:")
    print(f"     Mismo día + misma sucursal: {len(dup_misma_sucursal)}")
    print(f"     Mismo día + distintas sucursales: {len(dup_dist_sucursal)}")

    all_dups_enrolled = dup_misma_sucursal + dup_dist_sucursal
    if all_dups_enrolled:
        for rut_norm, d, entries in sorted(all_dups_enrolled, key=lambda x: (x[1] or date.min,)):
            tipo = "MISMA SUCURSAL" if len(set(e['branch'] for e in entries)) == 1 else "DISTINTAS SUCURSALES"
            print(f"\n     [{tipo}] RUT: {entries[0]['rut']} | {entries[0]['name']} | Fecha: {d}")
            for e in entries:
                print(f"       ShiftID={e['shift_id']} Branch={e['branch']} Shift={e['shift']}")
    else:
        print("     (ninguno)")

    print(f"\n  5. Duplicados en hoja Inscritos:")
    print(f"     Pares (RUT, ShiftID) duplicados: {len(dup_pair)}")
    print(f"     RUT con mismo día distintos turnos: {len(dup_inscritos_branch)}")

    all_dups_inscritos = dup_pair + [(k[0], None, v) for k, v in [] ]
    if dup_pair:
        print("\n     Pares (RUT, ShiftID) duplicados:")
        for (rut_norm, sid), entries in sorted(dup_pair):
            print(f"       RUT={entries[0]['rut']} ShiftID={sid} ({len(entries)} veces) Nombre={entries[0]['name']}")

    if dup_inscritos_branch:
        print("\n     RUT mismo día distintos turnos en Inscritos:")
        for rut_norm, d, entries in sorted(dup_inscritos_branch, key=lambda x: (x[1] or date.min,)):
            print(f"       RUT={entries[0]['rut']} Fecha={d} Nombre={entries[0]['name']}")
            for e in entries:
                t_info = turno_date_map.get(e['shift_id'], {})
                branch = e['branch'] or (t_info.get('branch', '') if t_info else '')
                print(f"         ShiftID={e['shift_id']} Branch={branch}")

    if not dup_pair and not dup_inscritos_branch:
        print("     (ninguno)")

if __name__ == '__main__':
    main()
