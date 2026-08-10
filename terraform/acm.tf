# ==============================================================================
# ACM — TLS Certificate (DNS-validated via Route 53)
#
# Requests a wildcard-capable certificate for `var.domain_name` and validates
# it automatically by writing CNAME records to the Route 53 hosted zone
# identified by `var.route53_zone_id`.
#
# `aws_acm_certificate_validation` blocks until AWS confirms the cert is issued
# (typically 1–3 minutes). The ALB listener depends on this resource so
# Terraform will not attach an unvalidated cert.
# ==============================================================================

resource "aws_acm_certificate" "main" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  # Subject Alternative Names — add the bare domain AND www for flexibility.
  subject_alternative_names = [
    "www.${var.domain_name}",
  ]

  # Rotate the cert before destroying the old one so there is never a gap.
  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "${local.name_prefix}-cert"
  }
}

# ---- DNS Validation Records --------------------------------------------------
# ACM emits one CNAME record per domain name covered by the cert.
# `for_each` on domain_validation_options dedups them (bare domain and www
# often share the same validation record).

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id = var.route53_zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.record]
  ttl     = 60

  allow_overwrite = true   # Safe to overwrite — ACM regenerates the same value
}

# ---- Wait for Certificate Issuance -------------------------------------------
# Terraform blocks here until ACM confirms the cert is ISSUED.
# The ALB HTTPS listener references this resource, not the certificate directly,
# so the entire apply blocks here rather than at listener creation.

resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}
