"""Compile and check pilot Bicep locally; never log in, deploy or write build files."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def one(template, kind):
    matches = [r for r in template['resources'] if r['type'] == kind]
    require(len(matches) == 1, f'Expected one {kind}')
    return matches[0]


def check(templates):
    foundation, app, monitoring = (templates[k] for k in ('foundation', 'app', 'monitoring'))
    params = app['parameters']
    require(params['externalIngress']['defaultValue'] is False, 'Public ingress must default off')
    for name in ('entraClientSecret', 'tokenStoreSasUrl'):
        require(params[name]['type'].lower() == 'securestring' and 'defaultValue' not in params[name],
                'Secrets must be required secure parameters')
    require(params['imageDigestHex']['minLength'] == params['imageDigestHex']['maxLength'] == 64,
            'Image digest length must be pinned')
    resource = one(app, 'Microsoft.App/containerApps')['properties']
    config, template = resource['configuration'], resource['template']
    require(config['ingress']['external'] == "[parameters('externalIngress')]", 'Ingress bypass')
    require(config['ingress']['allowInsecure'] is False, 'HTTPS required')
    require(template['scale']['minReplicas'] == 0 and template['scale']['maxReplicas'] == 1,
            'Unexpected replica limits')
    require(config['activeRevisionsMode'] == 'Single', 'Single revision required')
    require(len(template['containers']) == 1, 'Only boundary container is allowed')
    container = template['containers'][0]
    env = {x['name']: x['value'] for x in container['env']}
    require(env['DTM_CLOUD'] == '0' and env['DTM_RUNTIME_MODE'] == 'hosted', 'Cloud-off hosted mode required')
    require('DTM_LOCAL_PILOT' not in env and '@sha256:' in container['image'], 'No local bypass or image tags')
    auth = one(app, 'Microsoft.App/containerApps/authConfigs')['properties']
    require(auth['platform']['enabled'] is True, 'Platform auth required')
    require(auth['globalValidation'] == {'unauthenticatedClientAction': 'Return401', 'excludedPaths': ['/healthz']},
            'Anonymous route expansion')
    validation = auth['identityProviders']['azureActiveDirectory']['validation']
    require(validation['defaultAuthorizationPolicy']['allowedPrincipals']['identities'] == ["[parameters('employeeObjectId')]"],
            'Only the assigned employee is allowed')
    require(auth['login']['nonce']['validateNonce'] is True, 'Nonce enforcement required')
    registry = one(foundation, 'Microsoft.ContainerRegistry/registries')['properties']
    require(registry['adminUserEnabled'] is False and registry['anonymousPullEnabled'] is False,
            'Registry must require identity')
    require(registry['roleAssignmentMode'] == 'LegacyRegistryPermissions', 'AcrPull requires registry RBAC mode')
    roles = [r for r in foundation['resources'] if r['type'] == 'Microsoft.Authorization/roleAssignments']
    require(len(roles) == 2, 'Runtime must have only two role assignments')
    for role in roles:
        scope = role['scope']
        require('Microsoft.ContainerRegistry/registries' in scope or
                'Microsoft.Storage/storageAccounts/tableServices/tables' in scope,
                'Runtime role scope broadened')
    for blob in [r for r in foundation['resources'] if r['type'].endswith('/containers')]:
        require(blob['properties']['publicAccess'] == 'None', 'Private blobs required')
    for name in ('enableLogAlerts', 'enableBudget'):
        require(monitoring['parameters'][name]['defaultValue'] is False, 'Monitoring must be opt-in after readiness')
    query = one(monitoring, 'Microsoft.Insights/scheduledQueryRules')['properties']['criteria']['allOf'][0]['query']
    require("parameters('appName')" in query and 'replace(' in query, 'Alert query must bind actual app name')
    for document in templates.values():
        outputs = json.dumps(document.get('outputs', {})).lower()
        require(not any(x in outputs for x in ('listkeys(', 'entraclientsecret', 'tokenstoresasurl')),
                'Credentials must not be deployment outputs')


def compile_templates(bicep):
    templates = {}
    for name in ('foundation', 'app', 'monitoring'):
        path = ROOT / 'packaging' / 'hosted' / 'azure' / f'{name}.bicep'
        result = subprocess.run([bicep, 'build', str(path), '--stdout'], capture_output=True, text=True, check=True)
        require(not result.stderr.strip(), f'{name}: compiler diagnostics:\n{result.stderr.strip()}')
        templates[name] = json.loads(result.stdout)
    return templates


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bicep', default='bicep', help='Local Bicep executable (no automatic installation)')
    args = parser.parse_args()
    check(compile_templates(args.bicep))
    print('PASS: 3 Bicep templates compile without warnings; auth, scope, secret and scale safeguards checked')
