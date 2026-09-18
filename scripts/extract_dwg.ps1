<#
Read-only extraction from an AutoCAD drawing via COM.

Attaches to a running AutoCAD instance. Either uses the drawing that is already
open (default) or opens -DwgPath read-only and closes it afterwards.

Outputs:
  <OutDir>\cad_summary.txt   document info, extents, layer list, entity histogram
  <OutDir>\cad_text.txt      every TEXT/MTEXT string with its position
  <OutDir>\cad_dims.txt      every dimension: measured value, text, position
  <OutDir>\cad_entities.csv  geometry of LINE/LWPOLYLINE/CIRCLE/ARC/SPLINE...

Nothing is written back to the drawing; only read-only COM properties are used.
Usage:
  powershell -File extract_dwg.ps1 -OutDir <dir> [-DwgPath <file.dwg>]
#>
param(
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$DwgPath
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Get-Acad {
    foreach ($id in @('AutoCAD.Application.24', 'AutoCAD.Application.23',
                      'AutoCAD.Application.22', 'AutoCAD.Application')) {
        try { return [Runtime.InteropServices.Marshal]::GetActiveObject($id) } catch { }
    }
    throw 'No running AutoCAD instance found'
}

$acad = Get-Acad
$opened = $false
trap {
    # 出错时也要关掉本脚本打开的图纸，避免在用户 AutoCAD 里留下只读窗口
    if ($opened -and $doc) { try { $doc.Close($false) } catch { } }
    throw
}
if ($DwgPath) {
    if (-not (Test-Path -LiteralPath $DwgPath)) { throw "DWG not found: $DwgPath" }
    $doc = $acad.Documents.Open((Resolve-Path -LiteralPath $DwgPath).Path, $false, $true)
    $opened = $true
} else {
    $doc = $acad.ActiveDocument
}

$summary = New-Object System.Collections.Generic.List[string]
$summary.Add("name: $($doc.Name)")
$summary.Add("path: $($doc.FullName)")
$summary.Add("saved: $($doc.Saved)")
$summary.Add("active layout: $($doc.ActiveLayout.Name)")
$summary.Add("modelspace entities: $($doc.ModelSpace.Count)")
$summary.Add("paperspace blocks: $($doc.Blocks.Count)")
$summary.Add("layers: $($doc.Layers.Count)")

# Extents
try {
    $min = $doc.GetVariable('EXTMIN')
    $max = $doc.GetVariable('EXTMAX')
    $summary.Add("EXTMIN: $($min -join ',')")
    $summary.Add("EXTMAX: $($max -join ',')")
    $summary.Add("INSUNITS: $($doc.GetVariable('INSUNITS'))")
    $summary.Add("DIMSCALE: $($doc.GetVariable('DIMSCALE'))")
    $summary.Add("LTSCALE: $($doc.GetVariable('LTSCALE'))")
} catch { $summary.Add("extents unavailable: $_") }

$summary.Add('')
$summary.Add('layers:')
foreach ($layer in $doc.Layers) {
    $summary.Add(("  {0}  color={1}  linetype={2}  on={3}" -f `
        $layer.Name, $layer.color, $layer.Linetype, (-not $layer.LayerOn)))
}

$texts = New-Object System.Collections.Generic.List[string]
$dims = New-Object System.Collections.Generic.List[string]
$geo = New-Object System.Collections.Generic.List[string]
$hist = @{}

function Get-Coord($pt) {
    return ('{0:F3},{1:F3},{2:F3}' -f $pt[0], $pt[1], $pt[2])
}

# Walk model space and every paper-space layout
$spaces = @{ 'Model' = $doc.ModelSpace }
foreach ($layout in $doc.Layouts) {
    try { $spaces["Layout:$($layout.Name)"] = $doc.Blocks.Item($layout.Block) } catch { }
}

foreach ($spaceName in $spaces.Keys) {
    $space = $spaces[$spaceName]
    foreach ($ent in $space) {
        $type = $ent.ObjectName
        $key = "$spaceName/$type"
        if ($hist.ContainsKey($key)) { $hist[$key]++ } else { $hist[$key] = 1 }

        try {
            switch -Regex ($type) {
                'AcDbText|AcDbMText|AcDbAttributeDefinition' {
                    $content = if ($type -eq 'AcDbMText') { $ent.TextString } else { $ent.TextString }
                    $texts.Add(("[{0}] {1} :: {2}" -f $spaceName, (Get-Coord $ent.InsertionPoint), $content))
                    break
                }
                'AcDbRotatedDimension|AcDbAlignedDimension|AcDb2LineAngularDimension|AcDbRadialDimension|AcDbDiametricDimension|AcDb3PointAngularDimension|AcDbOrdinateDimension' {
                    $dims.Add(("[{0}] {1} :: measurement={2} text={3} :: {4}" -f `
                        $spaceName, $type, $ent.Measurement, $ent.TextString, (Get-Coord $ent.TextPosition)))
                    break
                }
                'AcDbLine' {
                    $geo.Add(("[{0}] LINE,{1},{2}" -f $spaceName, (Get-Coord $ent.StartPoint), (Get-Coord $ent.EndPoint)))
                    break
                }
                'AcDbPolyline|AcDb2dPolyline|AcDb3dPolyline' {
                    $pts = @()
                    try {
                        $coords = $ent.Coordinates
                        if ($type -eq 'AcDbPolyline') {
                            for ($i = 0; $i -lt $coords.Count; $i += 2) {
                                $pts += ('{0:F3},{1:F3}' -f $coords[$i], $coords[$i + 1])
                            }
                        } else {
                            for ($i = 0; $i -lt $coords.Count; $i += 3) {
                                $pts += ('{0:F3},{1:F3},{2:F3}' -f $coords[$i], $coords[$i + 1], $coords[$i + 2])
                            }
                        }
                    } catch { }
                    $geo.Add(("[{0}] {1},closed={2},{3}" -f $spaceName, $type, $ent.Closed, ($pts -join ' ')))
                    break
                }
                'AcDbCircle' {
                    $geo.Add(("[{0}] CIRCLE,c={1},r={2:F3}" -f $spaceName, (Get-Coord $ent.Center), $ent.Radius))
                    break
                }
                'AcDbArc' {
                    $geo.Add(("[{0}] ARC,c={1},r={2:F3},{3:F3}..{4:F3}" -f `
                        $spaceName, (Get-Coord $ent.Center), $ent.Radius, $ent.StartAngle, $ent.EndAngle))
                    break
                }
                'AcDbBlockReference' {
                    $geo.Add(("[{0}] INSERT,{1},{2},scale={3},rot={4}" -f `
                        $spaceName, $ent.Name, (Get-Coord $ent.InsertionPoint), $ent.XScaleFactor, $ent.Rotation))
                    break
                }
                'AcDbSpline' {
                    try {
                        $pts = @()
                        for ($i = 0; $i -lt $ent.NumberOfControlPoints; $i++) {
                            $p = $ent.GetControlPoint($i)
                            $pts += ('{0:F3},{1:F3},{2:F3}' -f $p[0], $p[1], $p[2])
                        }
                        $geo.Add(("[{0}] SPLINE,{1}" -f $spaceName, ($pts -join ' ')))
                    } catch {
                        $geo.Add(("[{0}] SPLINE,<ctrls={1}>" -f $spaceName, $ent.NumberOfControlPoints))
                    }
                    break
                }
                'AcDbHatch' {
                    $geo.Add(("[{0}] HATCH,pattern={1},loops={2}" -f $spaceName, $ent.PatternName, $ent.NumberOfLoops))
                    break
                }
            }
        } catch {
            $geo.Add(("[{0}] {1},<error: {2}>" -f $spaceName, $type, $_.Exception.Message))
        }
    }
}

$summary.Add('')
$summary.Add('entity histogram:')
foreach ($k in ($hist.Keys | Sort-Object)) { $summary.Add(("  {0} = {1}" -f $k, $hist[$k])) }

[IO.File]::WriteAllLines((Join-Path $OutDir 'cad_summary.txt'), $summary, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllLines((Join-Path $OutDir 'cad_text.txt'), $texts, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllLines((Join-Path $OutDir 'cad_dims.txt'), $dims, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllLines((Join-Path $OutDir 'cad_entities.csv'), $geo, [Text.UTF8Encoding]::new($false))

Write-Output ("texts={0} dims={1} geometry={2}" -f $texts.Count, $dims.Count, $geo.Count)

if ($opened) { $doc.Close($false) }
