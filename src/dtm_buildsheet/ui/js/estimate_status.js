// Shared estimate milestones for Projects and Operations. Linking is not sending.
function estimateStatus(vehicle = {}) {
  const linked = Boolean(vehicle.qbo_estimate_id || vehicle.qb_estimate_id);
  const transaction = String(vehicle.qbo_estimate_status || '').toLowerCase();
  if (vehicle.acceptance_status === 'accepted') return {key: 'estimate-accepted', label: 'Accepted'};
  if (!linked) return {key: 'estimate-unlinked', label: 'No Estimate Connected'};
  if (['declined', 'rejected', 'closed'].includes(transaction)) {
    return {key: 'estimate-closed', label: transaction === 'closed' ? 'Estimate Closed' : 'Estimate Declined'};
  }
  if (transaction === 'accepted') return {key: 'estimate-accepted', label: 'Accepted'};
  if (vehicle.qbo_estimate_sent_status === 'sent') return {key: 'estimate-sent', label: 'Estimate Sent'};
  return {key: 'estimate-created', label: 'Estimate Created'};
}

function estimateGroupStatus(vehicles = []) {
  if (!vehicles.length) return estimateStatus();
  const statuses = vehicles.map(estimateStatus);
  if (statuses.every(status => status.key === statuses[0].key)) return statuses[0];
  const counts = new Map();
  statuses.forEach(status => counts.set(status.label, (counts.get(status.label) || 0) + 1));
  return {key: 'estimate-mixed', label: [...counts].map(([label, count]) => `${count}/${vehicles.length} ${label}`).join(' · ')};
}

function estimateSendDetail(vehicle) {
  if (!(vehicle.qbo_estimate_id || vehicle.qb_estimate_id)) return 'No Estimate Connected';
  if (vehicle.qbo_estimate_sent_status === 'sent') {
    const time = vehicle.qbo_estimate_sent_at;
    return time ? `Sent ${new Date(time).toLocaleString()}` : 'Sent · date unavailable';
  }
  return vehicle.qbo_estimate_sent_status === 'not_confirmed'
    ? 'Sending not confirmed by QuickBooks' : 'Send history unavailable';
}
