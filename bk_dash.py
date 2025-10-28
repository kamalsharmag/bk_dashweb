# field_dashboard.py
from flask import Flask, render_template_string, request, send_file
import pandas as pd
import io, json, re

app = Flask(__name__)
DF_STORE = {}

# ---------------- HTML TEMPLATE ----------------
TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Field Team Retailer Dashboard</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
  <style>
    body { background: linear-gradient(135deg,#f0f7ff,#fff6f9); font-family: Inter, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial; }
    .header { background:#0b5ed7; color:white; padding:14px; border-radius:10px; margin-top:12px; margin-bottom:18px; text-align:center;}
    .kpi-card { border-radius:12px; box-shadow:0 6px 18px rgba(10,10,20,0.06); height:140px; display:flex; flex-direction:column; justify-content:center; align-items:center; color:white; }
    .kpi-title { font-size:0.9rem; opacity:0.95; }
    .kpi-value { font-size:1.9rem; font-weight:700; margin-top:6px; }
    .download-btn { margin-top:8px; font-size:12px; background:rgba(255,255,255,0.18); border:none; color:white; padding:6px 8px; border-radius:8px; }
    .download-btn:hover { background:rgba(255,255,255,0.28); }
    .filter-row { margin-bottom:18px; }
    table { font-size:0.85rem; }
  </style>
</head>
<body>
<div class="container">
  <div class="header"><h4 class="mb-0">📊 Field Team Retailer Dashboard</h4></div>

  {% if not df_json %}
    <div class="card p-4">
      <form action="/upload" method="post" enctype="multipart/form-data" class="row g-3">
        <div class="col-md-9">
          <input type="file" name="file" accept=".xlsx,.xls" class="form-control" required>
        </div>
        <div class="col-md-3 text-end">
          <button class="btn btn-primary w-100">Upload & Show Dashboard</button>
        </div>
        <div class="col-12">
          <small class="text-muted">Expected columns: Sn, Agent_ID, Retailer_ID, Name, State, District, Mob_No, Pin_Code, Address, Status, Sub_Status, Actionable_Remark, Active_YTD, Active_MTD, Retailer_Type, Onboarded_Date, FE_DI, FE_DI_Mob_No, Area_Head, AH_Mobile, AH_Email_ID</small>
        </div>
      </form>
    </div>
  {% else %}
    <div class="row filter-row">
      <div class="col-md-3"><select id="stateFilter" class="form-select"><option value="">All States</option></select></div>
      <div class="col-md-3"><select id="districtFilter" class="form-select"><option value="">All Districts</option></select></div>
      <div class="col-md-3"><select id="typeFilter" class="form-select"><option value="">All Retailer Types</option></select></div>
      <div class="col-md-3"><button id="resetFilters" class="btn btn-outline-secondary w-100">Reset Filters</button></div>
    </div>

    <!-- KPI cards row -->
    <div class="row g-3" id="kpiRow"></div>

    <!-- Status KPI row -->
    <div class="row g-3 mt-2" id="statusRow"></div>

    <div class="card mt-4 p-3">
      <div class="table-responsive">
        <table id="dataTable" class="table table-striped table-bordered"></table>
      </div>
    </div>
  {% endif %}
</div>

<script>
const RAW = {{ df_json|safe }};

// Helper: unique sorted
function uniq(arr){ return [...new Set(arr.filter(x=>x && String(x).trim()!=='').map(String))].sort(); }

function populateFilters(){
  const states = uniq(RAW.map(r=>r.State));
  const districts = uniq(RAW.map(r=>r.District));
  const types = uniq(RAW.map(r=>r.Retailer_Type));
  states.forEach(s=> $('#stateFilter').append(`<option value="${s}">${s}</option>`));
  districts.forEach(d=> $('#districtFilter').append(`<option value="${d}">${d}</option>`));
  types.forEach(t=> $('#typeFilter').append(`<option value="${t}">${t}</option>`));
}

function canonicalStatus(raw){
  // Mirror server-side mapping if needed client-side.
  if(!raw) return 'Others';
  const s = String(raw).trim().toLowerCase();
  if(s.includes('kyc') || (s.includes('qualified') && s.includes('kyc'))) return 'Qualified-(KYC Pending)';
  if(s.includes('approval pending') || (s.includes('pending') && !s.includes('kyc'))) return 'Approval Pending';
  if(s.includes('reject') || s.includes('rejected')) return 'Approval Rejected';
  if(s.includes('on-board') || s.includes('on boarded') || (s.includes('on') && s.includes('board'))) return 'On-Boarded';
  if(s.includes('replac') || s.includes('replacement')) return 'Replacment required';
  return 'Others';
}

function updateDashboard(){
  const st = $('#stateFilter').val();
  const dt = $('#districtFilter').val();
  const tp = $('#typeFilter').val();

  const filtered = RAW.filter(r=> (!st || r.State===st) && (!dt || r.District===dt) && (!tp || r.Retailer_Type===tp) );

  // status buckets
  const statusKeys = ['Approval Pending','Approval Rejected','On-Boarded','Qualified-(KYC Pending)','Replacment required'];
  const counts = { 'Approval Pending':0,'Approval Rejected':0,'On-Boarded':0,'Qualified-(KYC Pending)':0,'Replacment required':0,'Others':0 };

  let ytd = 0, mtd = 0;
  const agentIds = [];
  filtered.forEach(r=>{
    const cs = canonicalStatus(r.Status);
    counts[cs] = (counts[cs]||0) + 1;
    ytd += Number(r.Active_YTD) || 0;
    mtd += Number(r.Active_MTD) || 0;
    if(r.Agent_ID !== '' && r.Agent_ID !== null && r.Agent_ID !== undefined) agentIds.push(String(r.Agent_ID));
  });

  const uniqueAgents = new Set(agentIds).size;
  const totalRecords = filtered.length;

  // KPI top row: Active YTD, Active MTD, Total Records, Unique Agents
  const kpiHtml = [
    { title:'Active YTD', value: Math.round(ytd), color:'linear-gradient(90deg,#1e8449,#2ecc71)' },
    { title:'Active MTD', value: Math.round(mtd), color:'linear-gradient(90deg,#0b74c9,#29b6f6)' },
    { title:'Total Records', value: totalRecords, color:'linear-gradient(90deg,#6f42c1,#8e44ad)' },
    { title:'Unique Agents', value: uniqueAgents, color:'linear-gradient(90deg,#d35400,#f39c12)' }
  ].map(k=>`
    <div class="col-md-3">
      <div class="kpi-card" style="background:${k.color}">
        <div class="kpi-title">${k.title}</div>
        <div class="kpi-value">${k.value}</div>
      </div>
    </div>
  `).join('');
  $('#kpiRow').html(kpiHtml);

  // Status cards (equal sized)
  const makeStatusCard = (title,key,clr)=>{
    // download form posts to /download with filters + status
    return `
      <div class="col-md-2">
        <div class="kpi-card" style="background:${clr}">
          <div class="kpi-title">${title}</div>
          <div class="kpi-value">${counts[key]||0}</div>
          <form method="post" action="/download" style="margin-top:8px;">
            <input type="hidden" name="status" value="${key}">
            <input type="hidden" name="state" value="${st||''}">
            <input type="hidden" name="district" value="${dt||''}">
            <input type="hidden" name="type" value="${tp||''}">
            <button class="download-btn" type="submit">⬇ Download CSV</button>
          </form>
        </div>
      </div>
    `;
  };

  const statusHtml = `
    ${makeStatusCard('Approval Pending','Approval Pending','linear-gradient(90deg,#45aaf2,#2b83d6)')}
    ${makeStatusCard('Approval Rejected','Approval Rejected','linear-gradient(90deg,#ff6b6b,#e74c3c)')}
    ${makeStatusCard('On-Boarded','On-Boarded','linear-gradient(90deg,#56cc9d,#2ecc71)')}
    ${makeStatusCard('KYC Pending','Qualified-(KYC Pending)','linear-gradient(90deg,#f6b93b,#f7b731)')}
    ${makeStatusCard('Replacement Req.','Replacment required','linear-gradient(90deg,#9b59b6,#8e44ad)')}
    ${makeStatusCard('Others','Others','linear-gradient(90deg,#95a5a6,#7f8c8d)')}
  `;
  $('#statusRow').html(statusHtml);

  // Table
  let cols = Object.keys(RAW[0]||{});
  let table = '<thead><tr>' + cols.map(c=>`<th>${c}</th>`).join('') + '</tr></thead><tbody>';
  filtered.forEach(r=>{
    table += '<tr>' + cols.map(c=>`<td>${r[c]===null? '': r[c]}</td>`).join('') + '</tr>';
  });
  table += '</tbody>';
  $('#dataTable').html(table);
}

$(function(){
  if(!RAW || RAW.length===0) return;
  populateFilters();
  updateDashboard();
  $('#stateFilter,#districtFilter,#typeFilter').on('change', updateDashboard);
  $('#resetFilters').on('click', function(){ $('#stateFilter,#districtFilter,#typeFilter').val(''); updateDashboard(); });
});
</script>
</body>
</html>
"""

# ---------------- Helper: normalize status server-side ----------------
def canonical_status(val):
    if pd.isna(val):
        return 'Others'
    s = str(val).strip().lower()
    # remove extra non-alphanumeric for easier matching
    s_norm = re.sub(r'[^a-z0-9\s\-\(\)]', ' ', s)
    if 'kyc' in s_norm or ('qualified' in s_norm and 'kyc' in s_norm):
        return 'Qualified-(KYC Pending)'
    if 'approval pending' in s_norm or ('pending' in s_norm and 'kyc' not in s_norm):
        return 'Approval Pending'
    if 'reject' in s_norm:
        return 'Approval Rejected'
    if 'on-board' in s_norm or 'on board' in s_norm or ('on' in s_norm and 'board' in s_norm):
        return 'On-Boarded'
    if 'replac' in s_norm or 'replacement' in s_norm:
        return 'Replacment required'
    return 'Others'

@app.route('/', methods=['GET'])
def index():
    return render_template_string(TEMPLATE, df_json=None)

@app.route('/upload', methods=['POST'])
def upload():
    f = request.files.get('file')
    if not f:
        return 'No file uploaded', 400
    try:
        in_memory = io.BytesIO(f.read())
        df = pd.read_excel(in_memory, engine='openpyxl')
    except Exception as e:
        return f'Error reading Excel: {e}', 400

    expected = [
        'Sn','Agent_ID','Retailer_ID','Name','State','District','Mob_No','Pin_Code','Address',
        'Status','Sub_Status','Actionable_Remark','Active_YTD','Active_MTD','Retailer_Type',
        'Onboarded_Date','FE_DI','FE_DI_Mob_No','Area_Head','AH_Mobile','AH_Email_ID'
    ]
    # ensure expected columns present
    for c in expected:
        if c not in df.columns:
            df[c] = ''

    # keep only expected order
    df = df[expected].fillna('')

    # numeric coercion for active columns
    for c in ['Active_YTD','Active_MTD']:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    # server-side canonical status column (helps avoid client/server mismatch)
    df['Status'] = df['Status'].apply(canonical_status)

    # Make all other non-numeric values strings to safely JSON serialize
    df = df.applymap(lambda x: x if isinstance(x, (int, float)) else ('' if pd.isna(x) else str(x)))

    DF_STORE['df'] = df.copy()
    DF_STORE['df_json'] = df.to_dict(orient='records')

    return render_template_string(TEMPLATE, df_json=json.dumps(DF_STORE['df_json']))

@app.route('/download', methods=['POST'])
def download():
    if 'df' not in DF_STORE:
        return 'No data uploaded', 400
    df = DF_STORE['df'].copy()

    status = request.form.get('status', '')
    state = request.form.get('state', '')
    district = request.form.get('district', '')
    rtype = request.form.get('type', '')

    # apply filters
    if state:
        df = df[df['State'] == state]
    if district:
        df = df[df['District'] == district]
    if rtype:
        df = df[df['Retailer_Type'] == rtype]

    if status and status != 'Others':
        df = df[df['Status'] == status]
    elif status == 'Others':
        valid = ["Approval Pending","Approval Rejected","On-Boarded","Qualified-(KYC Pending)","Replacment required"]
        df = df[~df['Status'].isin(valid)]

    out = io.BytesIO()
    # send CSV for easier immediate use
    df.to_csv(out, index=False)
    out.seek(0)
    filename = (status or 'others') + '_data.csv'
    return send_file(out, as_attachment=True, download_name=filename, mimetype='text/csv')

if __name__ == '__main__':
    app.run(debug=True)
