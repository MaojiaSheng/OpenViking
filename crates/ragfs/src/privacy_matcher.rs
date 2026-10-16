//! High-throughput replacement of registered sensitive values in UTF-8 text.
//!
//! This module deliberately knows nothing about OpenViking users, Privacy
//! paths, or authorization. Callers provide opaque patterns and replacement
//! references; RAGFS owns only automaton construction and text rewriting.

use aho_corasick::{AhoCorasick, AhoCorasickBuilder, MatchKind};
use std::collections::HashSet;

/// Replacement emitted for one non-overlapping leftmost-longest match.
#[derive(Clone, PartialEq, Eq)]
pub struct PrivacyReplacement {
    /// Match start as a Unicode character offset.
    pub start: usize,
    /// Match end as an exclusive Unicode character offset.
    pub end: usize,
    /// Opaque reference or ambiguity placeholder inserted into the output.
    pub reference: String,
}

/// Sanitized text and metadata for its replacements.
#[derive(Clone, PartialEq, Eq)]
pub struct PrivacySanitizeResult {
    /// Rewritten UTF-8 text.
    pub content: String,
    /// Non-overlapping replacements in source order.
    pub replacements: Vec<PrivacyReplacement>,
    /// Reference candidates for ambiguous values that occurred in the input.
    pub ambiguous_references: Vec<Vec<String>>,
}

#[derive(Clone)]
enum PatternTarget {
    Reference(String),
    Ambiguous(Vec<String>),
}

/// Immutable Aho-Corasick matcher for one Privacy catalog revision.
pub struct PrivacyMatcher {
    matcher: Option<AhoCorasick>,
    targets: Vec<PatternTarget>,
    ambiguous_placeholder: String,
}

impl PrivacyMatcher {
    /// Build a matcher from `(sensitive value, candidate references)` entries.
    ///
    /// Candidate references are sorted and deduplicated. One candidate produces
    /// a normal replacement; multiple candidates produce the supplied ambiguity
    /// placeholder and are reported in the result. Empty patterns and entries
    /// without references are rejected.
    pub fn new(
        entries: Vec<(String, Vec<String>)>,
        ambiguous_placeholder: impl Into<String>,
    ) -> Result<Self, String> {
        let mut patterns = Vec::with_capacity(entries.len());
        let mut targets = Vec::with_capacity(entries.len());
        let mut seen_patterns = HashSet::with_capacity(entries.len());

        for (pattern, mut references) in entries {
            if pattern.is_empty() {
                return Err("privacy match pattern must not be empty".to_string());
            }
            if !seen_patterns.insert(pattern.clone()) {
                return Err("privacy match patterns must be unique".to_string());
            }
            references.sort_unstable();
            references.dedup();
            if references.is_empty() {
                return Err("privacy match pattern requires at least one reference".to_string());
            }
            patterns.push(pattern);
            targets.push(if references.len() == 1 {
                PatternTarget::Reference(references.pop().expect("one reference remains"))
            } else {
                PatternTarget::Ambiguous(references)
            });
        }

        let matcher = if patterns.is_empty() {
            None
        } else {
            Some(
                AhoCorasickBuilder::new()
                    .match_kind(MatchKind::LeftmostLongest)
                    .build(patterns)
                    .map_err(|err| format!("failed to build Privacy matcher: {err}"))?,
            )
        };
        Ok(Self {
            matcher,
            targets,
            ambiguous_placeholder: ambiguous_placeholder.into(),
        })
    }

    /// Rewrite all non-overlapping leftmost-longest matches.
    pub fn sanitize(&self, content: &str) -> PrivacySanitizeResult {
        let Some(matcher) = &self.matcher else {
            return PrivacySanitizeResult {
                content: content.to_string(),
                replacements: Vec::new(),
                ambiguous_references: Vec::new(),
            };
        };

        let matches: Vec<_> = matcher.find_iter(content).collect();
        if matches.is_empty() {
            return PrivacySanitizeResult {
                content: content.to_string(),
                replacements: Vec::new(),
                ambiguous_references: Vec::new(),
            };
        }

        let extra_capacity = matches.len().saturating_mul(32);
        let mut rewritten = String::with_capacity(content.len().saturating_add(extra_capacity));
        let mut replacements = Vec::with_capacity(matches.len());
        let mut ambiguous_references = Vec::new();
        let mut source_byte_cursor = 0;
        let mut source_char_cursor = 0;

        for matched in matches {
            let start = matched.start();
            let end = matched.end();
            rewritten.push_str(&content[source_byte_cursor..start]);
            source_char_cursor += content[source_byte_cursor..start].chars().count();
            let char_start = source_char_cursor;
            source_char_cursor += content[start..end].chars().count();
            let char_end = source_char_cursor;

            let target = &self.targets[matched.pattern().as_usize()];
            let reference = match target {
                PatternTarget::Reference(reference) => reference.clone(),
                PatternTarget::Ambiguous(candidates) => {
                    ambiguous_references.push(candidates.clone());
                    self.ambiguous_placeholder.clone()
                }
            };
            rewritten.push_str(&reference);
            replacements.push(PrivacyReplacement {
                start: char_start,
                end: char_end,
                reference,
            });
            source_byte_cursor = end;
        }
        rewritten.push_str(&content[source_byte_cursor..]);

        PrivacySanitizeResult {
            content: rewritten,
            replacements,
            ambiguous_references,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn matcher(entries: Vec<(&str, Vec<&str>)>) -> PrivacyMatcher {
        PrivacyMatcher::new(
            entries
                .into_iter()
                .map(|(value, refs)| {
                    (
                        value.to_string(),
                        refs.into_iter().map(str::to_string).collect(),
                    )
                })
                .collect(),
            "{{ov_privacy:ambiguous}}",
        )
        .unwrap()
    }

    #[test]
    fn uses_leftmost_longest_and_unicode_character_offsets() {
        let matcher = matcher(vec![
            ("秘密", vec!["short"]),
            ("秘密值", vec!["long"]),
            ("token", vec!["token-ref"]),
        ]);
        let result = matcher.sanitize("前缀秘密值 token");
        assert_eq!(result.content, "前缀long token-ref");
        assert_eq!(result.replacements.len(), 2);
        assert_eq!(
            (result.replacements[0].start, result.replacements[0].end),
            (2, 5)
        );
        assert_eq!(
            (result.replacements[1].start, result.replacements[1].end),
            (6, 11)
        );
    }

    #[test]
    fn reports_ambiguity_without_exposing_pattern() {
        let matcher = matcher(vec![("secret", vec!["ref-b", "ref-a", "ref-a"])]);
        let result = matcher.sanitize("x secret y");
        assert_eq!(result.content, "x {{ov_privacy:ambiguous}} y");
        assert_eq!(result.ambiguous_references, vec![vec!["ref-a", "ref-b"]]);
    }

    #[test]
    fn empty_catalog_is_a_noop() {
        let matcher = PrivacyMatcher::new(Vec::new(), "ambiguous").unwrap();
        let result = matcher.sanitize("unchanged");
        assert_eq!(result.content, "unchanged");
        assert!(result.replacements.is_empty());
    }
}
