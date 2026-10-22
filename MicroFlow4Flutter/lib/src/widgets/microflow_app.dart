import 'package:flutter/material.dart';

import '../model/project_model.dart';
import '../runtime/microflow_runtime.dart';

class MicroFlowApp extends StatefulWidget {
  const MicroFlowApp({super.key, required this.runtime, this.theme});

  final MicroFlowRuntime runtime;
  final ThemeData? theme;

  @override
  State<MicroFlowApp> createState() => _MicroFlowAppState();
}

class _MicroFlowAppState extends State<MicroFlowApp> {
  @override
  void initState() {
    super.initState();
    widget.runtime.addListener(_changed);
    widget.runtime.start();
  }

  @override
  void dispose() {
    widget.runtime.removeListener(_changed);
    super.dispose();
  }

  void _changed() => setState(() {});

  @override
  Widget build(BuildContext context) {
    final page = widget.runtime.currentPage;
    final built = page.builder(
      PageBuildContext(page: page, arguments: widget.runtime.currentArguments),
    );
    if (built is! Widget) {
      return MaterialApp(
        theme: widget.theme,
        home: Scaffold(
          body: Center(
            child: Text('Page ${page.id} returned a non-Widget value.'),
          ),
        ),
      );
    }
    return MaterialApp(theme: widget.theme, home: built);
  }
}
