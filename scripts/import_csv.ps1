<#
.SYNOPSIS
  Importa um CSV (do seu PC) para o banco do app fcsd como uma tabela,
  associando a uma Tabela Diamante (Diamond Layer) e/ou DataMart.

  Copia o CSV para dentro do container, roda o importador Python e limpa o temporário.

.EXAMPLE
  .\scripts\import_csv.ps1 .\pagamentos.csv -DiamondLayer Financeiro
  .\scripts\import_csv.ps1 .\dados.csv -Datamart default -Mode replace
  .\scripts\import_csv.ps1 .\vendas.csv -DiamondLayer Vendas -Table fato_vendas -Sep ';'
#>
param(
  [Parameter(Mandatory = $true, Position = 0)] [string]$Csv,
  [string]$DiamondLayer,
  [string]$Datamart,
  [string]$Table,
  [ValidateSet('replace', 'append')] [string]$Mode = 'replace',
  [string]$Sep = 'auto',
  [string]$Encoding = 'utf-8',
  [string]$OwnerLogin,
  [string]$Container = 'fcsd-app'
)

if (-not (Test-Path $Csv)) { Write-Error "CSV nao encontrado: $Csv"; exit 1 }
if (-not $DiamondLayer -and -not $Datamart) {
  Write-Error "Informe -DiamondLayer e/ou -Datamart (onde a tabela ficara acessivel)."; exit 2
}

# Subdir unico + nome original preservado (o nome da tabela vem do nome do arquivo).
$tmpDir = "/tmp/fcsd_imp_$PID"
$tmp = "$tmpDir/" + [System.IO.Path]::GetFileName($Csv)

docker exec $Container mkdir -p $tmpDir | Out-Null
docker cp "$Csv" "${Container}:$tmp"
if ($LASTEXITCODE -ne 0) { Write-Error "Falha no docker cp"; exit 1 }

$pyArgs = @($tmp)
if ($Table)        { $pyArgs += @('--table', $Table) }
if ($DiamondLayer) { $pyArgs += @('--diamond-layer', $DiamondLayer) }
if ($Datamart)     { $pyArgs += @('--datamart', $Datamart) }
$pyArgs += @('--mode', $Mode, '--sep', $Sep, '--encoding', $Encoding)
if ($OwnerLogin)   { $pyArgs += @('--owner-login', $OwnerLogin) }

docker exec $Container python /app/scripts/import_csv.py @pyArgs
$rc = $LASTEXITCODE

docker exec $Container rm -f $tmp | Out-Null
exit $rc
