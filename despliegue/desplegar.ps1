<#
.SYNOPSIS
  Despliega el backend de Cards for DemocraXSSy en una OCI Container Instance.

.DESCRIPTION
  1. Verifica que la imagen exista en Docker Hub para ARM64 (la forma A1 es ARM).
  2. Si ya hay una Container Instance con el mismo nombre, la elimina y espera a que
     se libere la IP privada fija (OCI no permite cambiar la imagen de una instancia).
  3. Crea la nueva instancia (A1, IP privada 10.0.8.50, IP pública solo para descargar
     la imagen; el puerto 3000 solo es accesible desde la VM del frontend).
  4. Espera a que quede ACTIVE y comprueba el servicio por HTTP y HTTPS a través del
     nginx de la VM (incluida la cabecera de CORS).

  Requisitos: OCI CLI configurada (oci setup config) e imagen ya publicada con
  docker buildx para linux/amd64 y linux/arm64.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File despliegue\desplegar.ps1 -Version v2
#>
param(
    [Parameter(Mandatory = $true)] [string] $Version,   # etiqueta de la imagen en Docker Hub (v2, v3, ...)
    [double] $Ocpus = 1,
    [double] $MemoriaGB = 1,
    [switch] $SinPreguntar                              # no pedir confirmación antes de eliminar
)

# "Continue": la CLI de OCI escribe avisos por la salida de error y en Windows PowerShell,
# con "Stop", eso detendría el script. Los errores reales se revisan con $LASTEXITCODE.
$ErrorActionPreference = "Continue"
# Docker Hub exige TLS 1.2 (Windows PowerShell 5.1 no siempre lo activa por defecto).
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ---------------------------------------------------------------- configuración (no son secretos)
$Nombre        = "democraxssy-backend"
$Compartimento = "ocid1.compartment.oc1..aaaaaaaaysash2rweran5rgjjorxiqwhazbqysxtca7nbifnv23ulzzlfjsa"
$Subred        = "ocid1.subnet.oc1.iad.aaaaaaaaxpgdd2ravm7c3lb3y6pjbsxotobxalajw3q5lwjb432jmllqh5qq"
$Dominio       = "IIEJ:US-ASHBURN-AD-1"
$Forma         = "CI.Standard.A1.Flex"
$IpPrivada     = "10.0.8.50"
$Repositorio   = "jaredcr10/democraxssy-backend"
$Api           = "api-democraxssy-anj.duckdns.org"

function Paso($n, $texto)  { Write-Host "`n[$n/5] $texto" -ForegroundColor Cyan }
function Ok($texto)        { Write-Host "      OK  $texto" -ForegroundColor Green }
function Info($texto)      { Write-Host "      $texto" -ForegroundColor Gray }
function Falla($texto)     { Write-Host "      ERROR  $texto" -ForegroundColor Red; exit 1 }

# Ruta del ejecutable de la CLI. Se llama siempre por esta ruta: una función llamada "Oci"
# taparía al programa "oci" (PowerShell no distingue mayúsculas) y se llamaría a sí misma.
$OciExe = (Get-Command oci -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $OciExe) { Write-Host "No se encontró la CLI de OCI (oci). Instálala primero." -ForegroundColor Red; exit 1 }

function InvocarOci {
    # Ejecuta la CLI de OCI y devuelve el JSON ya convertido. Corta el script si falla.
    $salida = & $OciExe @args 2>&1
    if ($LASTEXITCODE -ne 0) { Falla ("oci " + ($args -join " ") + "`n" + ($salida -join "`n")) }
    $texto = ($salida | Where-Object { $_ -is [string] }) -join "`n"
    if ($texto.Trim()) { return $texto | ConvertFrom-Json } else { return $null }
}

function EstadoInstancia($id) {
    $r = InvocarOci container-instances container-instance get --container-instance-id $id
    return $r.data.'lifecycle-state'
}

$imagen = "docker.io/${Repositorio}:$Version"
Write-Host "Despliegue de $Nombre  |  $Forma ($Ocpus OCPU, $MemoriaGB GB)  |  $IpPrivada  |  $imagen" -ForegroundColor White

# ---------------------------------------------------------------- 1. imagen
Paso 1 "Verificando la imagen en Docker Hub..."
try {
    $tag = Invoke-RestMethod -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop `
        -Uri "https://hub.docker.com/v2/repositories/$Repositorio/tags/$Version"
} catch {
    Falla "No existe la etiqueta '$Version' en Docker Hub. Publica primero con:`n      docker buildx build --platform linux/amd64,linux/arm64 -t ${Repositorio}:$Version --push ."
}
$arqs = @($tag.images | ForEach-Object { "$($_.os)/$($_.architecture)" })
Info ("Arquitecturas: " + ($arqs -join ", "))
if ($arqs -notcontains "linux/arm64") { Falla "La imagen no tiene versión linux/arm64; la forma A1 es ARM y fallaría." }
Ok "La imagen existe y tiene versión ARM64"

# Antes de tocar nada, confirmar que esta versión de la CLI acepta todos los parámetros.
$ayuda = (& $OciExe container-instances container-instance create --help 2>&1 | Out-String)
foreach ($p in @("--availability-domain", "--shape-config", "--vnics", "--containers", "--container-restart-policy", "--display-name")) {
    if ($ayuda -notmatch [regex]::Escape($p)) { Falla "La CLI de OCI no reconoce '$p'. Actualízala o avisa antes de seguir." }
}
Ok "La CLI de OCI acepta todos los parámetros"

# ---------------------------------------------------------------- 2. instancia anterior
Paso 2 "Buscando una Container Instance anterior llamada '$Nombre'..."
$lista = InvocarOci container-instances container-instance list --compartment-id $Compartimento --all
$anteriores = @($lista.data.items | Where-Object {
    $_.'display-name' -eq $Nombre -and $_.'lifecycle-state' -notin @("DELETED", "DELETING")
})
if ($anteriores.Count -eq 0) {
    Ok "No hay instancia anterior"
} else {
    foreach ($ant in $anteriores) {
        Info "Encontrada: $($ant.id)  estado $($ant.'lifecycle-state')"
        if (-not $SinPreguntar) {
            $resp = Read-Host "      Se va a ELIMINAR esa instancia (las partidas en curso se pierden). Continuar? (s/n)"
            if ($resp -ne "s") { Write-Host "      Cancelado." -ForegroundColor Yellow; exit 0 }
        }
        InvocarOci container-instances container-instance delete --container-instance-id $ant.id --force | Out-Null
        Info "Eliminando... (espera a que se libere la IP $IpPrivada)"
        $limite = (Get-Date).AddMinutes(10)
        do {
            Start-Sleep -Seconds 10
            $estado = EstadoInstancia $ant.id
            Info "estado: $estado"
            if ((Get-Date) -gt $limite) { Falla "La instancia no terminó de eliminarse en 10 minutos." }
        } while ($estado -ne "DELETED")
        Ok "Instancia anterior eliminada"
    }
}

# ---------------------------------------------------------------- 3. crear
Paso 3 "Creando la Container Instance..."
# Los parámetros complejos van en archivos JSON (file://) para evitar problemas de comillas en Windows.
$tmp = Join-Path $env:TEMP "democraxssy-despliegue"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
@{ ocpus = $Ocpus; memoryInGBs = $MemoriaGB } | ConvertTo-Json | Set-Content -Encoding ascii "$tmp\forma.json"
ConvertTo-Json -Depth 5 @(@{
    subnetId           = $Subred
    privateIp          = $IpPrivada
    isPublicIpAssigned = $true      # necesaria para descargar la imagen de docker.io
    displayName        = "$Nombre-vnic"
}) | Set-Content -Encoding ascii "$tmp\vnics.json"
ConvertTo-Json -Depth 5 @(@{
    displayName = "api"
    imageUrl    = $imagen
}) | Set-Content -Encoding ascii "$tmp\contenedores.json"

$intentos = 0
while ($true) {
    $intentos++
    $salida = & $OciExe container-instances container-instance create `
        --compartment-id $Compartimento `
        --availability-domain $Dominio `
        --display-name $Nombre `
        --shape $Forma `
        --shape-config "file://$tmp\forma.json" `
        --vnics "file://$tmp\vnics.json" `
        --containers "file://$tmp\contenedores.json" `
        --container-restart-policy ALWAYS 2>&1
    if ($LASTEXITCODE -eq 0) { break }
    $error_texto = ($salida -join "`n")
    if ($intentos -lt 4 -and $error_texto -match "(?i)ip|conflict|in use") {
        Info "OCI todavía no libera la IP $IpPrivada; reintento en 20 s ($intentos/3)..."
        Start-Sleep -Seconds 20
        continue
    }
    Falla "No se pudo crear la instancia:`n$error_texto"
}
$creada = (($salida | Where-Object { $_ -is [string] }) -join "`n") | ConvertFrom-Json
$id = $creada.data.id
if (-not $id) {   # por si la CLI no devuelve el recurso, se busca por nombre
    $lista = InvocarOci container-instances container-instance list --compartment-id $Compartimento --all
    $id = ($lista.data.items | Where-Object {
        $_.'display-name' -eq $Nombre -and $_.'lifecycle-state' -notin @("DELETED", "DELETING", "FAILED")
    } | Select-Object -First 1).id
}
Ok "Instancia creada: $id"

# ---------------------------------------------------------------- 4. esperar ACTIVE
Paso 4 "Esperando a que la instancia quede ACTIVE (descarga la imagen de docker.io)..."
$limite = (Get-Date).AddMinutes(10)
do {
    Start-Sleep -Seconds 10
    $estado = EstadoInstancia $id
    Info "estado: $estado"
    if ($estado -eq "FAILED") {
        Falla "La instancia falló. Revisa en la consola: Container Instances > $Nombre > Work requests."
    }
    if ((Get-Date) -gt $limite) { Falla "La instancia no quedó ACTIVE en 10 minutos." }
} while ($estado -ne "ACTIVE")
Ok "Instancia ACTIVE"

# ---------------------------------------------------------------- 5. salud
Paso 5 "Comprobando el backend a través de nginx (HTTP y HTTPS)..."
foreach ($url in @("https://$Api/api/salud", "http://$Api/api/salud")) {
    $limite = (Get-Date).AddMinutes(3)
    while ($true) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Method Head -Uri $url -TimeoutSec 5 -MaximumRedirection 0 -ErrorAction Stop `
                -Headers @{ Origin = "https://democraxssy-anj.duckdns.org" }
            $cors = $r.Headers["Access-Control-Allow-Origin"]
            Ok "$url  ->  $($r.StatusCode)  (CORS: $cors)"
            break
        } catch {
            if ((Get-Date) -gt $limite) { Falla "$url no respondió 200: $($_.Exception.Message)" }
            Info "$url todavía no responde; reintento en 5 s..."
            Start-Sleep -Seconds 5
        }
    }
}

Write-Host "`nListo: $Nombre $Version desplegado en $IpPrivada y publicado en https://$Api y http://$Api" -ForegroundColor Green
