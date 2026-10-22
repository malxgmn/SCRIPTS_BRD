<?php
// SCRIPTS/get_tenants.php
// Script ini digunakan oleh setup.py untuk mengambil data subdomain secara dinamis.

require __DIR__ . '/../vendor/autoload.php';
$app = require_once __DIR__ . '/../bootstrap/app.php';

use App\Models\Subdomain;
use App\Models\Setting;

$kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
$kernel->bootstrap();

$tenants = [];

// 1. Ambil data Default (Tenant ID 0)
$settings = Setting::pluck('value', 'key')->all();
if (!empty($settings) && isset($settings['bot_token'])) {
    $tenants[] = [
        'id' => 0,
        'api_id' => $settings['api_id'] ?? '',
        'api_hash' => $settings['api_hash'] ?? '',
        'bot_token' => $settings['bot_token'] ?? '',
        'bot_username' => $settings['bot_username'] ?? '',
        'admin_ids' => $settings['admin_ids'] ?? (isset($settings['admin']) ? $settings['admin'] : '')
    ];
}

// 2. Ambil data Subdomain (Tenant ID > 0)
$subdomains = Subdomain::all();
foreach ($subdomains as $s) {
    $tenants[] = [
        'id' => $s->id,
        'api_id' => $s->api_id,
        'api_hash' => $s->api_hash,
        'bot_token' => $s->bot_token,
        'bot_username' => $s->bot_username,
        'admin_ids' => $s->admin_ids
    ];
}

echo json_encode($tenants);
