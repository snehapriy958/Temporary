import React from 'react';
import { AlertTriangle, RefreshCw, ArrowLeft } from 'lucide-react';

export class CorridorErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[CorridorErrorBoundary] 3D Scene crashed:', error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-[500px] p-8 bg-white border border-rose-200 rounded-xl text-center shadow-sm">
          <div className="p-4 bg-rose-50 rounded-full border border-rose-200 mb-4">
            <AlertTriangle className="h-10 w-10 text-rose-600" />
          </div>
          <h3 className="text-lg font-bold text-slate-900 mb-2">3D Corridor Rendering Interrupted</h3>
          <p className="text-sm text-slate-600 max-w-md mb-4">
            A rendering or WebGL initialization exception occurred while constructing the 3D corridor geometry.
          </p>
          <div className="bg-rose-50 px-4 py-2.5 rounded-lg border border-rose-200 text-xs font-mono text-rose-800 max-w-xl mb-6 overflow-x-auto text-left">
            {this.state.error?.message || 'Unknown WebGL context error'}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={this.handleRetry}
              className="flex items-center gap-2 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold transition border border-slate-300"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Retry 3D Scene
            </button>
            {this.props.onReturnTo2D && (
              <button
                onClick={this.props.onReturnTo2D}
                className="flex items-center gap-2 px-4 py-2 bg-teal-600 hover:bg-teal-500 text-white rounded-lg text-xs font-semibold transition shadow-sm"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                Return to 2D Dashboard
              </button>
            )}
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
