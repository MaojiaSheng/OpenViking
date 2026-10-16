use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use ragfs::privacy_matcher::PrivacyMatcher;

fn benchmark_privacy_matcher(c: &mut Criterion) {
    let mut group = c.benchmark_group("privacy_matcher");
    for pattern_count in [100usize, 1_000] {
        let entries: Vec<_> = (0..pattern_count)
            .map(|index| {
                (
                    format!("mock-secret-{index:06}-value"),
                    vec![format!("{{{{privacy-ref-{index}}}}}")],
                )
            })
            .collect();
        let matcher = PrivacyMatcher::new(entries, "{{ov_privacy:ambiguous}}").unwrap();
        let mut content = "ordinary context without a registered value\n".repeat(20_000);
        content.push_str("credential=mock-secret-000042-value\n");
        group.throughput(Throughput::Bytes(content.len() as u64));
        group.bench_with_input(
            BenchmarkId::from_parameter(pattern_count),
            &content,
            |bench, input| {
                bench.iter(|| matcher.sanitize(black_box(input)));
            },
        );
    }
    group.finish();
}

criterion_group!(benches, benchmark_privacy_matcher);
criterion_main!(benches);
