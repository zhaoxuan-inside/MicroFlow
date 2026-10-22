/// Platform-neutral project model shared by tooling, runtime and renderers.
class ProjectModel {
  const ProjectModel({
    required this.projectId,
    required this.schemaVersion,
    required this.releaseId,
    required this.pages,
    this.entryPageId,
    this.metadata = const {},
  });

  final String projectId;
  final String schemaVersion;
  final String releaseId;
  final String? entryPageId;
  final List<PageDefinition> pages;
  final Map<String, Object?> metadata;

  PageDefinition? page(String id) {
    for (final page in pages) {
      if (page.id == id) return page;
    }
    return null;
  }

  Map<String, Object?> toJson() => {
    'project_id': projectId,
    'schema_version': schemaVersion,
    'release_id': releaseId,
    if (entryPageId != null) 'entry_page_id': entryPageId,
    'pages': pages.map((page) => page.toJson()).toList(growable: false),
    'metadata': metadata,
  };
}

class PageDefinition {
  const PageDefinition({
    required this.id,
    required this.route,
    required this.title,
    required this.builder,
    this.parameters = const {},
    this.metadata = const {},
  });

  final String id;
  final String route;
  final String title;
  final PageBuilder builder;
  final Map<String, Object?> parameters;
  final Map<String, Object?> metadata;

  Map<String, Object?> toJson() => {
    'id': id,
    'route': route,
    'title': title,
    'parameters': parameters,
    'metadata': metadata,
  };
}

typedef PageBuilder = Object Function(PageBuildContext context);

class PageBuildContext {
  const PageBuildContext({required this.page, required this.arguments});

  final PageDefinition page;
  final Object? arguments;
}
