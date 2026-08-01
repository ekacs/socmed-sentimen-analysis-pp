# create_internal_cert.ps1
# Skrip PowerShell untuk membuat dan menginstal Self-Signed Code Signing Certificate di Windows (Internal)

param (
    [string]$FilePath = ""
)

$CertSubject = "CN=SocMed Sentiment Analysis Internal Code Signing"

# Cek apakah sertifikat sudah ada
$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $CertSubject } | Select-Object -First 1

if (-not $cert) {
    Write-Host "[CERT] Membuat Self-Signed Code Signing Certificate baru..."
    $cert = New-SelfSignedCertificate -Subject $CertSubject `
        -Type CodeSigningCert `
        -CertStoreLocation Cert:\CurrentUser\My `
        -KeyUsage DigitalSignature `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -NotAfter (Get-Date).AddYears(5)
}

# Trust Certificate di CurrentUser Root & TrustedPublisher
$rootStore = Get-Item Cert:\CurrentUser\Root
$rootStore.Open("ReadWrite")
$rootStore.Add($cert)
$rootStore.Close()

$pubStore = Get-Item Cert:\CurrentUser\TrustedPublisher
$pubStore.Open("ReadWrite")
$pubStore.Add($cert)
$pubStore.Close()

Write-Host "[CERT] Sertifikat Digital Siap. Thumbprint:" $cert.Thumbprint

if ($FilePath -and (Test-Path $FilePath)) {
    Write-Host "[SIGNING] Menandatangani berkas:" $FilePath
    $signResult = Set-AuthenticodeSignature -FilePath $FilePath -Certificate $cert -HashAlgorithm SHA256
    Write-Host "[SIGNING] Status Penandatanganan:" $signResult.Status
}
