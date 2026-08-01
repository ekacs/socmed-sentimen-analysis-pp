# sign_target.ps1
param (
    [string]$TargetPath
)

$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -like "*SocMed*" } | Select-Object -First 1

if (-not $cert) {
    Write-Host "[CERT] Membuat sertifikat baru..."
    $cert = New-SelfSignedCertificate -Subject "CN=SocMed Sentiment Analysis Internal Code Signing" -Type CodeSigningCert -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)
    
    $store1 = Get-Item Cert:\CurrentUser\Root
    $store1.Open("ReadWrite")
    $store1.Add($cert)
    $store1.Close()
    
    $store2 = Get-Item Cert:\CurrentUser\TrustedPublisher
    $store2.Open("ReadWrite")
    $store2.Add($cert)
    $store2.Close()
}

Write-Host "Cert Thumbprint:" $cert.Thumbprint

if (Test-Path $TargetPath) {
    Write-Host "Menandatangani berkas:" $TargetPath
    $sig = Set-AuthenticodeSignature -FilePath $TargetPath -Certificate $cert
    Write-Host "Hasil Status Signature:" $sig.Status
} else {
    Write-Host "File tidak ditemukan:" $TargetPath
}
